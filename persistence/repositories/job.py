"""Reconciliation job repository.

Implements tenant-scoped job lifecycle management, cursor-paginated job listing,
cancellation requests, attempt-fenced completion, and compatibility helpers for
PostgreSQL SECURITY DEFINER worker functions and SQLite emulation.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_JOB, generate_public_id
from persistence.models import (
    OrganisationMembership,
    ReconciliationJob,
    ReconciliationRun,
)
from persistence.repositories.base import RecordNotFoundError, scoped_select
from persistence.repositories.cursor import decode_cursor, encode_cursor
from persistence.uow import insert_with_public_id_retry


class InvalidJobStateError(Exception):
    """Raised when an illegal job lifecycle transition is attempted."""


class JobFencingError(Exception):
    """Raised when a job update fails due to lease generation or attempt token fencing."""


def create_reconciliation_job(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    max_attempts: int = 3,
    scheduled_at: datetime | None = None,
) -> ReconciliationJob:
    """Enqueue a new reconciliation job in 'queued' status for a run."""
    context.require_run_mutation("create")
    now = scheduled_at or datetime.now(UTC)

    return insert_with_public_id_retry(
        session,
        lambda: ReconciliationJob(
            public_id=generate_public_id(PREFIX_JOB),
            organisation_id=context.organisation_id,
            run_id=run_id,
            created_by_principal_id=context.principal_id,
            status="queued",
            stage="queued",
            max_attempts=max_attempts,
            attempt_count=0,
            lease_generation=0,
            scheduled_at=now,
            created_at=now,
            updated_at=now,
            is_cancelled=False,
        ),
        expected_constraint="reconciliation_jobs_public_id_key",
    )


def get_job_by_id(
    session: Session, context: TenantContext, job_id: int
) -> ReconciliationJob | None:
    """Retrieve a job by internal surrogate ID, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationJob, context).where(ReconciliationJob.id == job_id)
    )


def get_job_by_public_id(
    session: Session, context: TenantContext, public_id: str
) -> ReconciliationJob | None:
    """Retrieve a job by opaque public ID, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationJob, context).where(ReconciliationJob.public_id == public_id)
    )


def get_job_by_run_id(
    session: Session, context: TenantContext, run_id: int
) -> ReconciliationJob | None:
    """Retrieve the job associated with a run, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationJob, context).where(ReconciliationJob.run_id == run_id)
    )


def list_jobs(
    session: Session,
    context: TenantContext,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[ReconciliationJob], str | None]:
    """List jobs for the current tenant using stable cursor pagination (created_at DESC, id DESC)."""
    stmt = scoped_select(ReconciliationJob, context)

    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            (ReconciliationJob.created_at < cursor_dt)
            | ((ReconciliationJob.created_at == cursor_dt) & (ReconciliationJob.id < cursor_id))
        )

    stmt = stmt.order_by(ReconciliationJob.created_at.desc(), ReconciliationJob.id.desc()).limit(
        limit + 1
    )

    rows = list(session.scalars(stmt).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_item = rows[-1]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return rows, next_cursor


def request_job_cancellation(
    session: Session, context: TenantContext, public_id: str
) -> ReconciliationJob:
    """Request cooperative cancellation of a job.

    If the job is still queued, immediately marks it cancelled and also updates the run.
    If the job is running, sets is_cancelled=True so the worker halts at the next fence.
    """
    context.require_run_mutation("cancel")
    job = get_job_by_public_id(session, context, public_id)
    if job is None:
        raise RecordNotFoundError(f"Reconciliation job {public_id!r} not found")

    if job.status in ("completed", "failed", "cancelled"):
        return job

    now = datetime.now(UTC)
    job.is_cancelled = True
    job.cancelled_at = now
    job.cancelled_by_principal_id = context.principal_id

    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "completed"
        # Also mark associated run as failed/aborted
        run = session.scalar(
            scoped_select(ReconciliationRun, context).where(ReconciliationRun.id == job.run_id)
        )
        if run and run.status == "initiated":
            run.status = "failed"
            run.error_code = "job_cancelled"
            run.error_summary = "Reconciliation job was cancelled by user before execution"
            run.failed_at = now

    session.flush()
    return job


def complete_job_fenced(
    session: Session,
    context: TenantContext,
    job_id: int,
    *,
    attempt_token: str,
    lease_generation: int,
    completed_at: datetime | None = None,
) -> None:
    """Complete a job atomically using attempt fencing within the tenant context.

    Must be called inside the single completion transaction with untangle_app.
    """
    now = completed_at or datetime.now(UTC)
    result = session.execute(
        text(
            """
            UPDATE reconciliation_jobs
            SET status = 'completed',
                stage = 'completed',
                completed_at = :completed_at,
                updated_at = :completed_at
            WHERE id = :job_id
              AND organisation_id = :org_id
              AND attempt_token = :attempt_token
              AND lease_generation = :lease_generation
              AND status = 'running'
            """
        ),
        {
            "job_id": job_id,
            "org_id": context.organisation_id,
            "attempt_token": attempt_token,
            "lease_generation": lease_generation,
            "completed_at": now,
        },
    )
    if result.rowcount == 0:
        raise JobFencingError(
            f"Fencing validation failed completing job {job_id}: lease expired or preempted"
        )


# ---------------------------------------------------------------------------
# Worker Function Adapters (PostgreSQL SECURITY DEFINER / SQLite Emulation)
# ---------------------------------------------------------------------------


def claim_next_job(
    session: Session,
    worker_id: str,
    lease_seconds: int = 60,
) -> dict[str, Any] | None:
    """Claim the next eligible queued or timed-out job.

    In PostgreSQL: executes fn_job_claim_next(:worker_id, :lease_seconds).
    In SQLite: performs atomic query and update emulation.
    """
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        attempt_token = secrets.token_hex(16)
        row = (
            session.execute(
                text(
                    "SELECT job_id, public_id, organisation_id, run_id, created_by_principal_id, "
                    "attempt_token, lease_generation, attempt_count "
                    "FROM fn_job_claim_next(:worker_id, :lease_seconds, :attempt_token)"
                ),
                {"worker_id": worker_id, "lease_seconds": lease_seconds, "attempt_token": attempt_token},
            )
            .mappings()
            .first()
        )
        if row and row["job_id"] is not None:
            session.commit()
            return dict(row)
        return None

    # SQLite emulation
    now = datetime.now(UTC)
    candidate = session.execute(
        select(ReconciliationJob)
        .where(
            (ReconciliationJob.status == "queued")
            | (
                (ReconciliationJob.status == "running")
                & (ReconciliationJob.lease_expires_at < now)
                & (ReconciliationJob.attempt_count < ReconciliationJob.max_attempts)
            )
        )
        .where(ReconciliationJob.is_cancelled.is_(False))
        .order_by(ReconciliationJob.scheduled_at.asc())
        .limit(1)
    ).scalar_one_or_none()

    if candidate is None:
        return None

    attempt_token = secrets.token_hex(16)
    candidate.worker_id = worker_id
    candidate.attempt_token = attempt_token
    candidate.lease_generation += 1
    candidate.attempt_count += 1
    candidate.status = "running"
    candidate.stage = "ingesting"
    if candidate.started_at is None:
        candidate.started_at = now
    candidate.last_heartbeat_at = now
    candidate.lease_expires_at = now + timedelta(seconds=lease_seconds)
    candidate.updated_at = now

    session.flush()
    result = {
        "job_id": candidate.id,
        "organisation_id": candidate.organisation_id,
        "run_id": candidate.run_id,
        "attempt_token": candidate.attempt_token,
        "lease_generation": candidate.lease_generation,
    }
    session.commit()
    return result


def heartbeat_job(
    session: Session,
    job_id: int,
    worker_id: str,
    attempt_token: str,
    lease_generation: int,
    lease_seconds: int = 60,
) -> bool:
    """Extend the lease of a currently running job."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = session.execute(
            text(
                "SELECT fn_job_heartbeat(:job_id, :attempt_token, :lease_generation, :lease_seconds)"
            ),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
                "lease_seconds": lease_seconds,
            },
        ).scalar()
        session.commit()
        return bool(res)

    now = datetime.now(UTC)
    result = session.execute(
        text(
            """
            UPDATE reconciliation_jobs
            SET last_heartbeat_at = :now,
                lease_expires_at = :lease_expires_at,
                updated_at = :now
            WHERE id = :job_id
              AND worker_id = :worker_id
              AND attempt_token = :attempt_token
              AND lease_generation = :lease_generation
              AND status = 'running'
            """
        ),
        {
            "job_id": job_id,
            "worker_id": worker_id,
            "attempt_token": attempt_token,
            "lease_generation": lease_generation,
            "now": now,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
        },
    )
    session.commit()
    return result.rowcount > 0


def check_job_cancellation(
    session: Session,
    job_id: int,
    attempt_token: str,
    lease_generation: int,
) -> bool:
    """Check if cancellation has been requested for this job."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = session.execute(
            text("SELECT fn_job_check_cancellation(:job_id, :attempt_token, :lease_generation)"),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
            },
        ).scalar()
        return bool(res)

    res = session.execute(
        text(
            """
            SELECT is_cancelled
            FROM reconciliation_jobs
            WHERE id = :job_id
              AND attempt_token = :attempt_token
              AND lease_generation = :lease_generation
            """
        ),
        {
            "job_id": job_id,
            "attempt_token": attempt_token,
            "lease_generation": lease_generation,
        },
    ).scalar()
    return bool(res)


def transition_job_stage(
    session: Session,
    job_id: int,
    worker_id: str,
    attempt_token: str,
    lease_generation: int,
    new_stage: str,
) -> bool:
    """Update the execution stage of a running job."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = session.execute(
            text(
                "SELECT fn_job_transition_stage(:job_id, :attempt_token, :lease_generation, :new_stage)"
            ),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
                "new_stage": new_stage,
            },
        ).scalar()
        session.commit()
        return bool(res)

    now = datetime.now(UTC)
    result = session.execute(
        text(
            """
            UPDATE reconciliation_jobs
            SET stage = :new_stage,
                updated_at = :now
            WHERE id = :job_id
              AND worker_id = :worker_id
              AND attempt_token = :attempt_token
              AND lease_generation = :lease_generation
              AND status = 'running'
            """
        ),
        {
            "job_id": job_id,
            "worker_id": worker_id,
            "attempt_token": attempt_token,
            "lease_generation": lease_generation,
            "new_stage": new_stage,
            "now": now,
        },
    )
    session.commit()
    return result.rowcount > 0


def fail_job(
    session: Session,
    job_id: int,
    worker_id: str,
    attempt_token: str,
    lease_generation: int,
    error_code: str,
    error_summary: str,
    retryable: bool = False,
) -> dict[str, Any]:
    """Fail or re-queue an attempt with fencing protection."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        result = session.execute(
            text(
                "SELECT fn_job_fail(:job_id, :attempt_token, :lease_generation, "
                ":error_code, :error_summary)"
            ),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
                "error_code": error_code,
                "error_summary": error_summary[:255],
            },
        ).scalar()
        session.commit()
        return {
            "is_permanent_failure": bool(result),
            "new_status": "failed" if result else "stale",
            "new_attempt_count": 0,
        }

    now = datetime.now(UTC)
    job = session.get(ReconciliationJob, job_id)
    if not job or job.attempt_token != attempt_token or job.lease_generation != lease_generation:
        return {"is_permanent_failure": False, "new_status": "stale", "new_attempt_count": 0}

    is_perm = not retryable or (job.attempt_count >= job.max_attempts)
    new_status = "failed" if is_perm else "queued"

    job.status = new_status
    job.error_code = error_code
    job.error_summary = error_summary[:255]
    job.updated_at = now

    if is_perm:
        job.failed_at = now
        job.stage = "completed"
        # Also fail run
        run = session.get(ReconciliationRun, job.run_id)
        if run and run.status in ("initiated", "running"):
            run.status = "failed"
            run.error_code = error_code
            run.error_summary = error_summary[:255]
            run.failed_at = now
    else:
        job.attempt_token = None
        job.worker_id = None
        job.lease_expires_at = None
        job.stage = "queued"

    session.commit()
    return {
        "is_permanent_failure": is_perm,
        "new_status": new_status,
        "new_attempt_count": job.attempt_count,
    }


def cancel_ack_job(
    session: Session,
    job_id: int,
    worker_id: str,
    attempt_token: str,
    lease_generation: int,
) -> bool:
    """Acknowledge job cancellation by worker."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = session.execute(
            text(
                "SELECT fn_job_cancel_ack(:job_id, :attempt_token, :lease_generation)"
            ),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
            },
        ).scalar()
        session.commit()
        return bool(res)

    now = datetime.now(UTC)
    job = session.get(ReconciliationJob, job_id)
    if not job or job.attempt_token != attempt_token or job.lease_generation != lease_generation:
        return False

    job.status = "cancelled"
    job.stage = "completed"
    job.updated_at = now

    run = session.get(ReconciliationRun, job.run_id)
    if run and run.status in ("initiated", "running"):
        run.status = "failed"
        run.error_code = "job_cancelled"
        run.error_summary = "Reconciliation job was cancelled"
        run.failed_at = now

    session.commit()
    return True


def revalidate_job_creator(
    session: Session,
    job_id: int,
    attempt_token: str,
    lease_generation: int,
) -> bool:
    """Verify that the creator of the job still holds active membership in the organisation."""
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = session.execute(
            text("SELECT fn_job_revalidate_creator(:job_id, :attempt_token, :lease_generation)"),
            {
                "job_id": job_id,
                "attempt_token": attempt_token,
                "lease_generation": lease_generation,
            },
        ).scalar()
        return bool(res)

    job = session.get(ReconciliationJob, job_id)
    if not job or job.attempt_token != attempt_token or job.lease_generation != lease_generation:
        return False

    membership = session.execute(
        select(OrganisationMembership).where(
            OrganisationMembership.organisation_id == job.organisation_id,
            OrganisationMembership.principal_id == job.created_by_principal_id,
            OrganisationMembership.status == "active",
        )
    ).scalar_one_or_none()

    return membership is not None

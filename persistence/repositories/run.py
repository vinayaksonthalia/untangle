"""Reconciliation run repository.

Implements tenant-scoped run creation, retrieval, concurrency-safe completion/failure,
and soft deletion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_RUN, generate_public_id
from persistence.models import ReconciliationRun
from persistence.repositories.base import RecordNotFoundError, scoped_select
from persistence.uow import insert_with_public_id_retry


class InvalidRunStateError(Exception):
    """Raised when an illegal run lifecycle transition is attempted."""


def create_run(
    session: Session,
    context: TenantContext,
    *,
    config_json: str = "{}",
    started_at: datetime | None = None,
) -> ReconciliationRun:
    """Create a new reconciliation run in 'initiated' status."""
    context.require_run_mutation("create")
    now = started_at or datetime.now(UTC)
    return insert_with_public_id_retry(
        session,
        lambda: ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=context.organisation_id,
            created_by_principal_id=context.principal_id,
            status="initiated",
            config_json=config_json,
            started_at=now,
            is_deleted=False,
        ),
        expected_constraint="reconciliation_runs_public_id_key",
    )


def get_run_by_id(
    session: Session, context: TenantContext, run_id: int
) -> ReconciliationRun | None:
    """Retrieve a run by internal surrogate ID, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationRun, context).where(ReconciliationRun.id == run_id)
    )


def get_run_by_public_id(
    session: Session, context: TenantContext, public_id: str
) -> ReconciliationRun | None:
    """Retrieve a run by opaque public ID, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationRun, context).where(ReconciliationRun.public_id == public_id)
    )


def list_runs(
    session: Session, context: TenantContext, limit: int = 50, offset: int = 0
) -> list[ReconciliationRun]:
    """List runs for the current organisation, ordered by most recent first."""
    stmt = (
        scoped_select(ReconciliationRun, context)
        .order_by(ReconciliationRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt).all())


def lock_run_for_update(
    session: Session, context: TenantContext, run_id: int
) -> ReconciliationRun | None:
    """Lock a run row FOR UPDATE, scoped to the current tenant."""
    return session.scalar(
        scoped_select(ReconciliationRun, context)
        .where(ReconciliationRun.id == run_id)
        .with_for_update()
    )


def complete_run(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    reconciliation_hash: str | None = None,
    bank_statement_hash: str | None = None,
    recon_report_hash: str | None = None,
    order_ledger_hash: str | None = None,
    evidence_pack_id: str | None = None,
    evidence_pack_version: str | None = None,
    completed_at: datetime | None = None,
) -> ReconciliationRun:
    """Mark a run as completed.

    Concurrency-safe and idempotent:
    - If already completed, returns existing run without raising or creating duplicates.
    - If in failed or aborted state, raises InvalidRunStateError.
    """
    context.require_run_mutation("complete")
    run = lock_run_for_update(session, context, run_id)
    if run is None:
        raise RecordNotFoundError(
            f"Run {run_id} not found for organisation {context.organisation_id}"
        )

    if run.status == "completed":
        return run

    if run.status in ("failed", "aborted"):
        raise InvalidRunStateError(
            f"Cannot complete run {run.public_id}: current status is {run.status!r}"
        )

    run.status = "completed"
    run.completed_at = completed_at or datetime.now(UTC)
    if reconciliation_hash is not None:
        run.reconciliation_hash = reconciliation_hash
    if bank_statement_hash is not None:
        run.bank_statement_hash = bank_statement_hash
    if recon_report_hash is not None:
        run.recon_report_hash = recon_report_hash
    if order_ledger_hash is not None:
        run.order_ledger_hash = order_ledger_hash
    if evidence_pack_id is not None:
        run.evidence_pack_id = evidence_pack_id
    if evidence_pack_version is not None:
        run.evidence_pack_version = evidence_pack_version

    session.flush()
    return run


def fail_run(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    error_code: str,
    error_summary: str,
    failed_at: datetime | None = None,
) -> ReconciliationRun:
    """Mark a run as failed.

    Concurrency-safe:
    - Never overwrites a completed run. If run is already completed, returns without modifying.
    - Sanitizes error code and summary (caller must ensure no raw exceptions or PII).
    """
    context.require_run_mutation("fail")
    run = lock_run_for_update(session, context, run_id)
    if run is None:
        raise RecordNotFoundError(
            f"Run {run_id} not found for organisation {context.organisation_id}"
        )

    if run.status == "completed":
        # Never overwrite a completed run with a failure
        return run

    run.status = "failed"
    run.failed_at = failed_at or datetime.now(UTC)
    run.error_code = error_code[:64]
    run.error_summary = error_summary[:255]

    session.flush()
    return run


def soft_delete_run(session: Session, context: TenantContext, public_id: str) -> bool:
    """Soft-delete a run by public ID within the tenant scope."""
    context.require_run_mutation("delete")
    run = get_run_by_public_id(session, context, public_id)
    if run is None:
        return False
    run.is_deleted = True
    run.deleted_at = datetime.now(UTC)
    session.flush()
    return True

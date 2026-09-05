"""Tests for reconciliation job repository, worker execution, leasing, and attempt fencing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.models import (
    OrganisationMembership,
    ReconciliationJob,
    ReconciliationRun,
)
from persistence.repositories.artifact import list_artifacts_for_run, save_uploaded_file_metadata
from persistence.repositories.job import (
    JobFencingError,
    cancel_ack_job,
    check_job_cancellation,
    claim_next_job,
    complete_job_fenced,
    create_reconciliation_job,
    get_job_by_public_id,
    heartbeat_job,
    list_jobs,
    request_job_cancellation,
    revalidate_job_creator,
    transition_job_stage,
)
from persistence.repositories.run import create_run
from persistence.storage import LocalStorageBackend, generate_input_object_key
from persistence.uow import UnitOfWork
from persistence.worker import ReconciliationWorker


@pytest.fixture
def local_storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path / "worker_storage")


@pytest.fixture(autouse=True)
def clean_queued_jobs(session_factory: sessionmaker[Session]):
    with session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(
                status="completed",
                stage="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        s.commit()
    yield
    with session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(
                status="completed",
                stage="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        s.commit()


def test_job_claim_heartbeat_and_stage_transitions(
    session_factory: sessionmaker[Session],
    worker_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    # 1. Create run and job
    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        job = create_reconciliation_job(uow.session, ctx, run.id)
        job_id = job.id
        job_public_id = job.public_id

    assert job_public_id.startswith("job_")

    # 2. Claim job
    with worker_session_factory() as w_session:
        claimed = claim_next_job(w_session, worker_id="worker_alpha", lease_seconds=30)
    assert claimed is not None
    assert claimed["job_id"] == job_id
    assert claimed["organisation_id"] == org_id
    assert claimed["lease_generation"] == 1
    attempt_token = claimed["attempt_token"]

    # Verify status in database
    with session_factory() as s:
        db_job = get_job_by_public_id(s, ctx, job_public_id)
        assert db_job is not None
        assert db_job.status == "running"
        assert db_job.stage == "ingesting"
        assert db_job.worker_id == "worker_alpha"
        assert db_job.attempt_count == 1
        assert db_job.lease_generation == 1

    # 3. Heartbeat
    with worker_session_factory() as w_session:
        ok = heartbeat_job(
            w_session,
            job_id=job_id,
            worker_id="worker_alpha",
            attempt_token=attempt_token,
            lease_generation=1,
            lease_seconds=60,
        )
    assert ok is True

    # 4. Stage transition
    with worker_session_factory() as w_session:
        st_ok = transition_job_stage(
            w_session,
            job_id=job_id,
            worker_id="worker_alpha",
            attempt_token=attempt_token,
            lease_generation=1,
            new_stage="reconciling",
        )
    assert st_ok is True

    with session_factory() as s:
        db_job = get_job_by_public_id(s, ctx, job_public_id)
        assert db_job.stage == "reconciling"
        complete_job_fenced(
            s,
            ctx,
            job_id,
            attempt_token=attempt_token,
            lease_generation=1,
        )
        s.commit()


def test_stale_worker_neutralization_and_preemption(
    session_factory: sessionmaker[Session],
    worker_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        job = create_reconciliation_job(uow.session, ctx, run.id, max_attempts=3)
        job_id = job.id

    # Worker 1 claims job
    with worker_session_factory() as w_session:
        claimed_1 = claim_next_job(w_session, worker_id="worker_slow", lease_seconds=10)
    assert claimed_1 is not None
    token_1 = claimed_1["attempt_token"]
    gen_1 = claimed_1["lease_generation"]
    assert gen_1 == 1

    # Simulate lease expiry by moving lease_expires_at into the past
    with session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.id == job_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=60))
        )
        s.commit()

    # Worker 2 claims the timed-out job
    with worker_session_factory() as w_session:
        claimed_2 = claim_next_job(w_session, worker_id="worker_fast", lease_seconds=30)
    assert claimed_2 is not None
    assert claimed_2["job_id"] == job_id
    token_2 = claimed_2["attempt_token"]
    gen_2 = claimed_2["lease_generation"]
    assert gen_2 == 2
    assert token_2 != token_1

    # Worker 1 wakes up and attempts a heartbeat -> rejected
    with worker_session_factory() as w_session:
        w1_hb = heartbeat_job(
            w_session,
            job_id=job_id,
            worker_id="worker_slow",
            attempt_token=token_1,
            lease_generation=gen_1,
        )
    assert w1_hb is False

    # Worker 1 attempts fenced completion -> raises JobFencingError
    with session_factory() as s:
        with pytest.raises(JobFencingError, match="Fencing validation failed"):
            complete_job_fenced(
                s,
                ctx,
                job_id,
                attempt_token=token_1,
                lease_generation=gen_1,
            )

    # Worker 2 completes job successfully
    with session_factory() as s:
        complete_job_fenced(
            s,
            ctx,
            job_id,
            attempt_token=token_2,
            lease_generation=gen_2,
        )
        s.commit()

    with session_factory() as s:
        finished_job = s.get(ReconciliationJob, job_id)
        assert finished_job.status == "completed"
        assert finished_job.stage == "completed"
        assert finished_job.lease_generation == 2


def test_revalidate_job_creator_revocation(
    session_factory: sessionmaker[Session],
    worker_session_factory: sessionmaker[Session],
    control_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        job = create_reconciliation_job(uow.session, ctx, run.id)
        job_id = job.id

    with worker_session_factory() as w_session:
        claimed = claim_next_job(w_session, "worker_check")
    assert claimed is not None

    # Before revocation: valid
    with worker_session_factory() as w_session:
        assert (
            revalidate_job_creator(
                w_session, job_id, claimed["attempt_token"], claimed["lease_generation"]
            )
            is True
        )

    # Revoke creator's membership in the organisation
    with control_session_factory() as c_session:
        c_session.execute(
            update(OrganisationMembership)
            .where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == ctx.principal_id,
            )
            .values(status="suspended")
        )
        c_session.commit()

    # After revocation: invalid
    with worker_session_factory() as w_session:
        assert (
            revalidate_job_creator(
                w_session, job_id, claimed["attempt_token"], claimed["lease_generation"]
            )
            is False
        )

    # Restore active membership for subsequent tests
    with control_session_factory() as c_session:
        c_session.execute(
            update(OrganisationMembership)
            .where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == ctx.principal_id,
            )
            .values(status="active")
        )
        c_session.commit()

    with session_factory() as s:
        complete_job_fenced(
            s,
            ctx,
            job_id,
            attempt_token=claimed["attempt_token"],
            lease_generation=claimed["lease_generation"],
        )
        s.commit()


def test_job_cancellation_cooperative(
    session_factory: sessionmaker[Session],
    worker_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        job = create_reconciliation_job(uow.session, ctx, run.id)
        job_id = job.id
        pub_id = job.public_id

    # Claim job
    with worker_session_factory() as w_session:
        claimed = claim_next_job(w_session, "worker_canceller")
    assert claimed is not None

    # User cancels job via API/repository
    with session_factory() as s:
        cancelled = request_job_cancellation(s, ctx, pub_id)
        assert cancelled.is_cancelled is True
        s.commit()

    # Worker checks cancellation
    with worker_session_factory() as w_session:
        is_canc = check_job_cancellation(
            w_session, job_id, claimed["attempt_token"], claimed["lease_generation"]
        )
        assert is_canc is True

        ack = cancel_ack_job(
            w_session,
            job_id,
            "worker_canceller",
            claimed["attempt_token"],
            claimed["lease_generation"],
        )
        assert ack is True

    with session_factory() as s:
        j = get_job_by_public_id(s, ctx, pub_id)
        assert j.status == "cancelled"
        assert j.stage == "completed"


def test_cursor_pagination_stability(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    # Create 5 runs and 5 jobs
    job_ids: list[int] = []
    with UnitOfWork(session_factory, ctx) as uow:
        for _ in range(5):
            run = create_run(uow.session, ctx)
            job = create_reconciliation_job(uow.session, ctx, run.id)
            job_ids.append(job.id)

    # Page 1 (limit 2)
    with session_factory() as s:
        page1, cursor1 = list_jobs(s, ctx, limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        # Page 2 (limit 2)
        page2, cursor2 = list_jobs(s, ctx, limit=2, cursor=cursor1)
        assert len(page2) == 2
        assert cursor2 is not None

        # Verify no overlap between page 1 and page 2
        p1_ids = [j.id for j in page1]
        p2_ids = [j.id for j in page2]
        assert set(p1_ids).isdisjoint(set(p2_ids))

        # Page 3 (limit 2)
        page3, cursor3 = list_jobs(s, ctx, limit=2, cursor=cursor2)
        assert len(page3) == 1
        assert cursor3 is None

        # Clean up dummy test jobs so they do not pollute subsequent tests
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.id.in_(job_ids))
            .values(
                status="completed",
                stage="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        s.commit()


def test_full_worker_reconciliation_cycle(
    session_factory: sessionmaker[Session],
    worker_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    local_storage: LocalStorageBackend,
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    bank_hash = hashlib.sha256(bank_bytes).hexdigest()
    recon_hash = hashlib.sha256(recon_bytes).hexdigest()
    ledger_hash = hashlib.sha256(ledger_bytes).hexdigest()

    # 1. Setup run and upload inputs into storage
    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        run_id = run.id
        run_pub = run.public_id

        # Store input bytes in storage
        k_bank = generate_input_object_key(
            f"org_{org_id}", run_pub, "bank_statement", bank_hash, "bank.csv"
        )
        k_recon = generate_input_object_key(
            f"org_{org_id}", run_pub, "recon_report", recon_hash, "recon.json"
        )
        k_ledger = generate_input_object_key(
            f"org_{org_id}", run_pub, "order_ledger", ledger_hash, "ledger.csv"
        )

        local_storage.store_bytes(k_bank, bank_bytes, "text/csv")
        local_storage.store_bytes(k_recon, recon_bytes, "application/json")
        local_storage.store_bytes(k_ledger, ledger_bytes, "text/csv")

        # Save uploaded file metadata records
        save_uploaded_file_metadata(
            uow.session,
            ctx,
            run_id,
            file_role="bank_statement",
            original_filename="bank.csv",
            content_type="text/csv",
            size_bytes=len(bank_bytes),
            sha256_checksum=bank_hash,
            backend="local",
            object_key=k_bank,
        )
        save_uploaded_file_metadata(
            uow.session,
            ctx,
            run_id,
            file_role="recon_report",
            original_filename="recon.json",
            content_type="application/json",
            size_bytes=len(recon_bytes),
            sha256_checksum=recon_hash,
            backend="local",
            object_key=k_recon,
        )
        save_uploaded_file_metadata(
            uow.session,
            ctx,
            run_id,
            file_role="order_ledger",
            original_filename="ledger.csv",
            content_type="text/csv",
            size_bytes=len(ledger_bytes),
            sha256_checksum=ledger_hash,
            backend="local",
            object_key=k_ledger,
        )

        job = create_reconciliation_job(uow.session, ctx, run_id)
        job_pub = job.public_id

    # 2. Worker executes run_once
    worker = ReconciliationWorker(
        app_session_factory=session_factory,
        worker_session_factory=worker_session_factory,
        storage=local_storage,
        worker_id="test_worker_e2e",
        lease_seconds=30,
    )

    processed = worker.run_once()
    assert processed is True

    # 3. Verify final state in database
    with session_factory() as s:
        db_job = get_job_by_public_id(s, ctx, job_pub)
        assert db_job is not None
        assert db_job.status == "completed"
        assert db_job.stage == "completed"
        assert db_job.completed_at is not None

        db_run = s.get(ReconciliationRun, run_id)
        assert db_run.status == "completed"
        assert db_run.reconciliation_hash is not None

        # Verify artifacts were promoted and stored
        arts = list_artifacts_for_run(s, ctx, run_id)
        assert len(arts) == 3
        types = {a.artifact_type for a in arts}
        assert types == {"tally_xml", "report_json", "certificate_json"}

        for a in arts:
            assert a.lifecycle_state == "active"
            assert a.object_key != ""
            # Verify data exists in storage
            raw = local_storage.retrieve_bytes(a.object_key)
            assert hashlib.sha256(raw).hexdigest() == a.content_sha256

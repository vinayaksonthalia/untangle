"""Three-phase transaction lifecycle, concurrency safety, and rollback tests."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.models import (
    ArtifactMetadata,
    AuditEvent,
    CertificateRecord,
    ReconciliationResult,
    ReconciliationRun,
    UploadedFileMetadata,
)
from persistence.repositories.audit import append_audit_event
from persistence.repositories.run import (
    InvalidRunStateError,
    complete_run,
    create_run,
    fail_run,
    get_run_by_public_id,
)
from persistence.service import TenantReconciliationService
from persistence.uow import UnitOfWork


@pytest.fixture
def sample_file_bytes() -> tuple[bytes, bytes, bytes]:
    """Load sample dataset files for testing."""
    data_dir = "data"
    bank_p = os.path.join(data_dir, "bank_statement.csv")
    recon_p = os.path.join(data_dir, "recon_report.json")
    ledger_p = os.path.join(data_dir, "order_ledger.csv")

    if not (os.path.exists(bank_p) and os.path.exists(recon_p) and os.path.exists(ledger_p)):
        import tempfile

        from generator.config import Config
        from generator.demo_dataset import write_demo_dataset

        tmp = tempfile.mkdtemp()
        base = write_demo_dataset(tmp, Config())
        bank_p = os.path.join(base, "bank_statement.csv")
        recon_p = os.path.join(base, "recon_report.json")
        ledger_p = os.path.join(base, "order_ledger.csv")

    with open(bank_p, "rb") as f:
        b_data = f.read()
    with open(recon_p, "rb") as f:
        r_data = f.read()
    with open(ledger_p, "rb") as f:
        l_data = f.read()
    return b_data, r_data, l_data


def test_three_phase_reconciliation_lifecycle_success(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    service = TenantReconciliationService(session_factory)
    result = service.execute_reconciliation(
        ctx,
        bank_bytes,
        recon_bytes,
        ledger_bytes,
    )

    run_public_id = result["run_public_id"]
    assert run_public_id.startswith("run_")

    # Inspect persisted state in DB
    with UnitOfWork(session_factory, ctx) as uow:
        run = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert run is not None
        assert run.status == "completed"
        assert run.completed_at is not None
        assert run.completed_at >= run.started_at
        assert run.reconciliation_hash == result["report_sha256"]

        # Verify uploaded files metadata
        files = list(
            uow.session.scalars(
                select(UploadedFileMetadata).where(UploadedFileMetadata.run_id == run.id)
            ).all()
        )
        assert len(files) == 3
        roles = {f.file_role for f in files}
        assert roles == {"bank_statement", "recon_report", "order_ledger"}

        # Verify reconciliation result
        res = uow.session.scalar(
            select(ReconciliationResult).where(ReconciliationResult.run_id == run.id)
        )
        assert res is not None
        assert res.report_sha256 == result["report_sha256"]

        # Verify certificate
        cert = uow.session.scalar(
            select(CertificateRecord).where(CertificateRecord.run_id == run.id)
        )
        assert cert is not None
        assert cert.content_sha256 == result["certificate"]["content_sha256"]

        # Verify artifacts
        artifacts = list(
            uow.session.scalars(
                select(ArtifactMetadata).where(ArtifactMetadata.run_id == run.id)
            ).all()
        )
        assert len(artifacts) == 2  # tally_xml and report_json

        # Verify audit events: run.initiated and run.completed
        events = list(
            uow.session.scalars(
                select(AuditEvent)
                .where(AuditEvent.subject_public_id == run_public_id)
                .order_by(AuditEvent.created_at.asc())
            ).all()
        )
        event_types = [e.event_type for e in events]
        assert "run.initiated" in event_types
        assert "run.completed" in event_types


def test_completed_run_is_never_overwritten_by_failed(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    service = TenantReconciliationService(session_factory)
    result = service.execute_reconciliation(ctx, bank_bytes, recon_bytes, ledger_bytes)
    run_public_id = result["run_public_id"]

    # Attempt to mark the already completed run as failed
    with UnitOfWork(session_factory, ctx) as uow:
        run = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert run is not None
        assert run.status == "completed"

        # Calling fail_run must preserve completed status
        failed_run = fail_run(
            uow.session,
            ctx,
            run.id,
            error_code="LATE_ERROR",
            error_summary="Should not overwrite",
        )
        assert failed_run.status == "completed"
        assert failed_run.error_code is None

    # The service-level failure recorder must not append a false failure event
    # after another worker has already committed completion.
    service._record_failure(
        ctx,
        run.id,
        run_public_id,
        error_code="LATE_ERROR",
        error_summary="sanitized",
    )
    with UnitOfWork(session_factory, ctx) as uow:
        false_failure = uow.session.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_public_id == run_public_id,
                AuditEvent.event_type == "run.failed",
            )
        )
        assert false_failure is None


def test_complete_run_is_idempotent(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    service = TenantReconciliationService(session_factory)
    result = service.execute_reconciliation(ctx, bank_bytes, recon_bytes, ledger_bytes)
    run_public_id = result["run_public_id"]

    # Calling complete_run again on completed run returns cleanly
    with UnitOfWork(session_factory, ctx) as uow:
        run = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert run is not None
        idempotent_run = complete_run(uow.session, ctx, run.id)
        assert idempotent_run.status == "completed"


def test_service_retry_on_completed_run_returns_persisted_certificate(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completed-run recovery branch in execute_reconciliation must return the
    certificate persisted at first completion, not a freshly re-issued one, and must not
    write duplicate completion rows or audit events."""
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    service = TenantReconciliationService(session_factory)
    first = service.execute_reconciliation(ctx, bank_bytes, recon_bytes, ledger_bytes)
    run_public_id = first["run_public_id"]
    persisted_content_sha = first["certificate"]["content_sha256"]

    with UnitOfWork(session_factory, ctx) as uow:
        run = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert run is not None
        run_id = run.id

    # Simulate a Phase-3 retry that resumes the SAME already-completed run: Phase 1 already
    # ran (skip its writes), and the engine "recomputes" a DIFFERENT certificate so we can
    # prove the persisted one — not the recomputed one — is returned.
    import persistence.service as service_mod

    monkeypatch.setattr(
        service_mod,
        "create_run",
        lambda session, context, **kw: SimpleNamespace(id=run_id, public_id=run_public_id),
    )
    monkeypatch.setattr(service_mod, "save_uploaded_file_metadata", lambda *a, **k: None)
    monkeypatch.setattr(service_mod, "append_audit_event", lambda *a, **k: None)
    tampered = {"certificate": {"tampered": True}, "content_sha256": "0" * 64, "signed": False}
    monkeypatch.setattr(service_mod, "issue_certificate", lambda report: tampered)

    retry = service.execute_reconciliation(ctx, bank_bytes, recon_bytes, ledger_bytes)

    # The authoritative persisted certificate is returned, never the recomputed/tampered one.
    assert retry["certificate"]["content_sha256"] == persisted_content_sha
    assert retry["certificate"]["content_sha256"] != "0" * 64

    # No duplicate one-to-one completion rows and no second run.completed audit event.
    with UnitOfWork(session_factory, ctx) as uow:
        certs = list(
            uow.session.scalars(
                select(CertificateRecord).where(CertificateRecord.run_id == run_id)
            ).all()
        )
        assert len(certs) == 1
        results = list(
            uow.session.scalars(
                select(ReconciliationResult).where(ReconciliationResult.run_id == run_id)
            ).all()
        )
        assert len(results) == 1
        completed_events = list(
            uow.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.subject_public_id == run_public_id,
                    AuditEvent.event_type == "run.completed",
                )
            ).all()
        )
        assert len(completed_events) == 1


def test_service_completion_does_not_overwrite_terminal_failed_run(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a run is already failed/aborted, a later completion attempt must refuse and must
    NOT overwrite the original failure diagnostics or append a duplicate run.failed event."""
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    # Create a run, fail it with known diagnostics, and record its single run.failed event.
    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        run_id = run.id
        run_public_id = run.public_id
    with UnitOfWork(session_factory, ctx) as uow:
        fail_run(
            uow.session,
            ctx,
            run_id,
            error_code="ORIGINAL_FAILURE",
            error_summary="original diagnostics",
        )
        append_audit_event(
            uow.session,
            ctx,
            event_type="run.failed",
            subject_type="reconciliation_run",
            subject_public_id=run_public_id,
            metadata_json={"error_code": "ORIGINAL_FAILURE"},
        )
    with UnitOfWork(session_factory, ctx) as uow:
        r = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert r is not None and r.status == "failed"
        original_failed_at = r.failed_at

    # Force a completion attempt to resume this already-terminal run.
    import persistence.service as service_mod

    monkeypatch.setattr(
        service_mod,
        "create_run",
        lambda session, context, **kw: SimpleNamespace(id=run_id, public_id=run_public_id),
    )
    monkeypatch.setattr(service_mod, "save_uploaded_file_metadata", lambda *a, **k: None)
    # append_audit_event stays REAL so a duplicate would actually be recorded if the bug existed.

    service = TenantReconciliationService(session_factory)
    with pytest.raises(InvalidRunStateError):
        service.execute_reconciliation(ctx, bank_bytes, recon_bytes, ledger_bytes)

    with UnitOfWork(session_factory, ctx) as uow:
        r = get_run_by_public_id(uow.session, ctx, run_public_id)
        assert r is not None
        assert r.status == "failed"
        assert r.error_code == "ORIGINAL_FAILURE"  # not overwritten by PERSISTENCE_FAILURE
        assert r.error_summary == "original diagnostics"
        assert r.failed_at == original_failed_at  # original timestamp preserved
        failed_events = list(
            uow.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.subject_public_id == run_public_id,
                    AuditEvent.event_type == "run.failed",
                )
            ).all()
        )
        assert len(failed_events) == 1  # no duplicate immutable audit event


def test_engine_failure_transitions_run_to_failed(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    service = TenantReconciliationService(session_factory)

    # Corrupt inputs to trigger engine InputError
    from engine.service import InputError

    corrupt_bytes = b"garbage_data_not_csv"
    with pytest.raises(InputError):
        service.execute_reconciliation(
            ctx,
            corrupt_bytes,
            corrupt_bytes,
            corrupt_bytes,
        )

    # Verify that the run exists and is marked 'failed'
    with UnitOfWork(session_factory, ctx) as uow:
        runs = list(
            uow.session.scalars(
                select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc())
            ).all()
        )
        assert len(runs) >= 1
        failed_run = runs[0]
        assert failed_run.status == "failed"
        assert failed_run.failed_at is not None
        assert failed_run.error_code == "RECONCILIATION_FAILED"
        assert failed_run.error_summary == (
            "The deterministic reconciliation engine could not process the input."
        )
        assert "garbage" not in failed_run.error_summary

        # Verify no partial results or certificates were committed
        res = uow.session.scalar(
            select(ReconciliationResult).where(ReconciliationResult.run_id == failed_run.id)
        )
        assert res is None

        # Verify audit event run.failed was recorded
        fail_event = uow.session.scalar(
            select(AuditEvent).where(
                AuditEvent.subject_public_id == failed_run.public_id,
                AuditEvent.event_type == "run.failed",
            )
        )
        assert fail_event is not None

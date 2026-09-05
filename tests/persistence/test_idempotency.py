"""Tests for reconciliation job submission, idempotency caching, and storage lifecycle."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.models import (
    IdempotencyRecord,
)
from persistence.repositories.idempotency import (
    IdempotencyCollisionError,
    get_idempotency_record,
)
from persistence.service import TenantReconciliationService
from persistence.storage import LocalStorageBackend


@pytest.fixture
def local_storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(base_dir=tmp_path / "idempotency_storage")


def test_idempotent_job_submission_lifecycle(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    local_storage: LocalStorageBackend,
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes

    service = TenantReconciliationService(session_factory, storage=local_storage)
    key = "idemp_key_alpha_123"

    # 1. First submission
    resp1, status1, is_replay1 = service.submit_reconciliation_job(
        ctx,
        bank_bytes,
        recon_bytes,
        ledger_bytes,
        idempotency_key=key,
        reporting_period_start=date(2026, 1, 1),
        reporting_period_end=date(2026, 1, 31),
    )

    assert status1 == 202
    assert is_replay1 is False
    assert resp1["status"] == "queued"
    job_id_1 = resp1["job_id"]
    run_id_1 = resp1["run_id"]

    # 2. Identical second submission with same key
    resp2, status2, is_replay2 = service.submit_reconciliation_job(
        ctx,
        bank_bytes,
        recon_bytes,
        ledger_bytes,
        idempotency_key=key,
        reporting_period_start=date(2026, 1, 1),
        reporting_period_end=date(2026, 1, 31),
    )

    assert status2 == 202
    assert is_replay2 is True
    assert resp2["job_id"] == job_id_1
    assert resp2["run_id"] == run_id_1

    # 3. Conflicting submission with same key but modified payload
    divergent_bank = bank_bytes + b"\ncorrupted,tail,row"
    with pytest.raises(IdempotencyCollisionError, match="conflicting request payload"):
        service.submit_reconciliation_job(
            ctx,
            divergent_bank,
            recon_bytes,
            ledger_bytes,
            idempotency_key=key,
            reporting_period_start=date(2026, 1, 1),
            reporting_period_end=date(2026, 1, 31),
        )

    # 4. New key creates a new independent run and job
    resp3, status3, is_replay3 = service.submit_reconciliation_job(
        ctx,
        bank_bytes,
        recon_bytes,
        ledger_bytes,
        idempotency_key="idemp_key_distinct_456",
        reporting_period_start=date(2026, 1, 1),
        reporting_period_end=date(2026, 1, 31),
    )
    assert status3 == 202
    assert is_replay3 is False
    assert resp3["job_id"] != job_id_1
    assert resp3["run_id"] != run_id_1


def test_expired_idempotency_record_is_cache_miss(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    key = "expired_key_test"

    # Seed an expired record
    with session_factory() as s:
        rec = IdempotencyRecord(
            organisation_id=org_id,
            idempotency_key=key,
            request_hash="a" * 64,
            job_id=1,
            run_id=1,
            response_status_code=202,
            response_json={"status": "queued"},
            created_at=datetime.now(UTC) - timedelta(days=2),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        s.add(rec)
        s.commit()

        # Query via repository: expired record is ignored
        found = get_idempotency_record(s, ctx, key)
        assert found is None


def test_invalid_period_order_rejected(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    local_storage: LocalStorageBackend,
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    bank_bytes, recon_bytes, ledger_bytes = sample_file_bytes
    service = TenantReconciliationService(session_factory, storage=local_storage)

    with pytest.raises(ValueError, match="cannot be after reporting_period_end"):
        service.submit_reconciliation_job(
            ctx,
            bank_bytes,
            recon_bytes,
            ledger_bytes,
            reporting_period_start=date(2026, 2, 1),
            reporting_period_end=date(2026, 1, 31),
        )

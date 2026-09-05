"""Schema integrity, CHECK constraints, and composite foreign key tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_FILE, PREFIX_INVESTIGATION, PREFIX_RUN, generate_public_id
from persistence.models import (
    InvestigationRecord,
    ReconciliationRun,
    UploadedFileMetadata,
)


def test_composite_foreign_key_rejects_cross_tenant_child(
    session: Session, tenant_a: tuple[TenantContext, int], tenant_b: tuple[TenantContext, int]
) -> None:
    """An investigation in Org B referencing a run in Org A must be rejected by composite FK."""
    ctx_a, org_a_id = tenant_a
    ctx_b, org_b_id = tenant_b

    # Create run belonging to Org A
    run_a = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_a_id,
        created_by_principal_id=ctx_a.principal_id,
        status="initiated",
        started_at=datetime.now(UTC),
    )
    session.add(run_a)
    session.commit()

    # Attempt to insert an investigation with Org B referencing Run A
    hostile_inv = InvestigationRecord(
        public_id=generate_public_id(PREFIX_INVESTIGATION),
        organisation_id=org_b_id,  # Org B!
        run_id=run_a.id,  # Run belonging to Org A!
        line_key="key_12345",
        root_cause="mdr_fee_drift",
        resolved=True,
        confidence=0.95,
        variance_paise=100,
        details_json={},
    )
    session.add(hostile_inv)

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_run_status_lifecycle_constraint_rejects_invalid_states(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    # 1. Invalid status string
    run_bad_status = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="invalid_status",
        started_at=now,
    )
    session.add(run_bad_status)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    # 2. 'completed' status without completed_at timestamp
    run_completed_no_timestamp = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="completed",
        started_at=now,
        completed_at=None,  # Missing!
    )
    session.add(run_completed_no_timestamp)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    # 3. 'failed' status without error_code
    run_failed_no_error = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="failed",
        started_at=now,
        failed_at=now,
        error_code=None,  # Missing!
    )
    session.add(run_failed_no_error)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_hash_constraints_reject_non_hexadecimal(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    run = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="initiated",
        started_at=now,
    )
    session.add(run)
    session.commit()

    # 64-character non-hex string (e.g. contains 'z')
    invalid_hash = "z" * 64
    file_record = UploadedFileMetadata(
        public_id=generate_public_id(PREFIX_FILE),
        organisation_id=org_id,
        run_id=run.id,
        file_role="bank_statement",
        original_filename="bank.csv",
        content_type="text/csv",
        size_bytes=1024,
        sha256_checksum=invalid_hash,
    )
    session.add(file_record)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_file_size_nonnegative_constraint(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    run = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="initiated",
        started_at=now,
    )
    session.add(run)
    session.commit()

    # Negative file size
    negative_size_file = UploadedFileMetadata(
        public_id=generate_public_id(PREFIX_FILE),
        organisation_id=org_id,
        run_id=run.id,
        file_role="bank_statement",
        original_filename="bank.csv",
        content_type="text/csv",
        size_bytes=-50,
        sha256_checksum="a" * 64,
    )
    session.add(negative_size_file)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_bigint_supports_large_monetary_values(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    """Verify that BIGINT handles up to 92 quintillion paise (over ₹920 lakh crore)."""
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    run = ReconciliationRun(
        public_id=generate_public_id(PREFIX_RUN),
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="initiated",
        started_at=now,
    )
    session.add(run)
    session.commit()

    large_variance = 9_000_000_000_000_000_000  # 9 quintillion paise
    inv = InvestigationRecord(
        public_id=generate_public_id(PREFIX_INVESTIGATION),
        organisation_id=org_id,
        run_id=run.id,
        line_key="key_huge_amount",
        root_cause="unexplained",
        resolved=False,
        confidence=0.0,
        variance_paise=large_variance,
        details_json={},
    )
    session.add(inv)
    session.commit()

    loaded = session.get(InvestigationRecord, inv.id)
    assert loaded is not None
    assert loaded.variance_paise == large_variance

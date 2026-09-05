"""Public ID collision detection and savepoint retry tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_RUN, generate_public_id
from persistence.models import ReconciliationRun
from persistence.uow import insert_with_public_id_retry


def test_public_id_collision_retry_succeeds_via_savepoint(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    # Pre-insert a run with fixed public ID
    fixed_id = generate_public_id(PREFIX_RUN)
    initial_run = ReconciliationRun(
        public_id=fixed_id,
        organisation_id=org_id,
        created_by_principal_id=ctx.principal_id,
        status="initiated",
        started_at=now,
    )
    session.add(initial_run)
    session.commit()

    # Generator function that yields the conflicting ID on first attempt, then a fresh ID
    attempts = 0

    def create_run_with_simulated_collision() -> ReconciliationRun:
        nonlocal attempts
        attempts += 1
        current_id = fixed_id if attempts == 1 else generate_public_id(PREFIX_RUN)
        return ReconciliationRun(
            public_id=current_id,
            organisation_id=org_id,
            created_by_principal_id=ctx.principal_id,
            status="initiated",
            started_at=now,
        )

    # Insertion should retry through savepoint and succeed
    result = insert_with_public_id_retry(
        session,
        create_run_with_simulated_collision,
        expected_constraint="reconciliation_runs_public_id_key",
        max_retries=3,
    )
    assert attempts == 2
    assert result.public_id != fixed_id
    session.commit()


def test_unrelated_integrity_error_is_not_retried(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    now = datetime.now(UTC)

    attempts = 0

    def create_invalid_run() -> ReconciliationRun:
        nonlocal attempts
        attempts += 1
        # Violates check constraint: status invalid
        return ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=org_id,
            created_by_principal_id=ctx.principal_id,
            status="illegal_status",
            started_at=now,
        )

    with pytest.raises(IntegrityError):
        insert_with_public_id_retry(
            session,
            create_invalid_run,
            expected_constraint="reconciliation_runs_public_id_key",
            max_retries=3,
        )

    # Must NOT have retried check constraint failure
    assert attempts == 1
    session.rollback()

"""PostgreSQL Row-Level Security (RLS) enforcement tests.

Exercises the permissive tenant_isolation_policy under an unprivileged database role.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.ids import PREFIX_RUN, generate_public_id
from persistence.models import ReconciliationRun
from persistence.uow import UnitOfWork


def test_row_level_security_enforcement(
    is_postgres: bool,
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    tenant_b: tuple[TenantContext, int],
) -> None:
    if not is_postgres:
        pytest.skip("Row-Level Security (RLS) requires a PostgreSQL instance")

    ctx_a, org_a_id = tenant_a
    ctx_b, org_b_id = tenant_b

    # 1. Tenant A creates Run A inside UnitOfWork (app.current_tenant_id = Org A)
    with UnitOfWork(session_factory, ctx_a) as uow_a:
        run_a = ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=org_a_id,
            created_by_principal_id=ctx_a.principal_id,
            status="initiated",
            started_at=datetime.now(UTC),
        )
        uow_a.session.add(run_a)

    # 2. Tenant B creates Run B inside UnitOfWork (app.current_tenant_id = Org B)
    with UnitOfWork(session_factory, ctx_b) as uow_b:
        run_b = ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=org_b_id,
            created_by_principal_id=ctx_b.principal_id,
            status="initiated",
            started_at=datetime.now(UTC),
        )
        uow_b.session.add(run_b)

    # 3. Same-tenant query succeeds: Tenant A sees Run A
    with UnitOfWork(session_factory, ctx_a) as uow_a:
        runs_a = list(uow_a.session.scalars(select(ReconciliationRun)).all())
        run_ids_a = {r.id for r in runs_a}
        assert run_a.id in run_ids_a
        assert run_b.id not in run_ids_a  # Tenant B's run must NOT be visible!

    # 4. Cross-tenant read returns 0 rows: Tenant B directly queries Run A by ID
    with UnitOfWork(session_factory, ctx_b) as uow_b:
        run_attempt = uow_b.session.scalar(
            select(ReconciliationRun).where(ReconciliationRun.id == run_a.id)
        )
        assert run_attempt is None  # RLS silently hides row belonging to Org A!

    # 5. Cross-tenant insert fails: Tenant A tries to insert a record with Org B id
    with pytest.raises((IntegrityError, ProgrammingError)):
        with UnitOfWork(session_factory, ctx_a) as uow_a:
            hostile_run = ReconciliationRun(
                public_id=generate_public_id(PREFIX_RUN),
                organisation_id=org_b_id,  # Spoofed Org B id!
                created_by_principal_id=ctx_a.principal_id,
                status="initiated",
                started_at=datetime.now(UTC),
            )
            uow_a.session.add(hostile_run)
            uow_a.session.flush()

    # 6. Unauthenticated query (no app.current_tenant_id set) returns 0 rows (fail-closed)
    with session_factory() as bare_session:
        bare_runs = list(bare_session.scalars(select(ReconciliationRun)).all())
        assert len(bare_runs) == 0  # Fail-closed: matches zero rows

"""Connection pool isolation and transaction-local setting safety tests."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.uow import UnitOfWork


def test_tenant_session_setting_clears_on_commit_and_rollback(
    is_postgres: bool,
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    if not is_postgres:
        pytest.skip("set_config testing requires PostgreSQL")

    ctx, org_id = tenant_a

    # 1. Successful transaction commit
    with UnitOfWork(session_factory, ctx) as uow:
        val = uow.session.execute(
            text("SELECT current_setting('app.current_tenant_id', true)")
        ).scalar()
        assert val == str(org_id)

    # Inspect connection after commit
    with session_factory() as sess:
        val_after = sess.execute(
            text("SELECT current_setting('app.current_tenant_id', true)")
        ).scalar()
        assert val_after in ("", None)

    # 2. Transaction rollback
    try:
        with UnitOfWork(session_factory, ctx) as uow:
            val_in_tx = uow.session.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            ).scalar()
            assert val_in_tx == str(org_id)
            raise ValueError("Intentional rollback trigger")
    except ValueError:
        pass

    # Inspect connection after rollback
    with session_factory() as sess:
        val_after_rb = sess.execute(
            text("SELECT current_setting('app.current_tenant_id', true)")
        ).scalar()
        assert val_after_rb in ("", None)

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from persistence.context import Role, TenantContext
from persistence.repositories.investigation import save_investigations
from persistence.uow import UnitOfWork


@pytest.mark.parametrize("value", [True, False, "100", 100.0, None])
def test_variance_paise_rejects_non_integer_values(
    session: Session, tenant_a: tuple[TenantContext, int], value: object
) -> None:
    context, _ = tenant_a
    with pytest.raises(ValueError, match="integer paise"):
        save_investigations(session, context, 1, [{"variance_paise": value}])


def test_uow_closes_session_when_enter_setup_fails() -> None:
    class BrokenSession:
        closed = False

        def begin(self) -> None:
            raise RuntimeError("boom")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    broken = BrokenSession()
    context = TenantContext(1, 1, Role.OWNER)
    with pytest.raises(RuntimeError, match="boom"):
        UnitOfWork(lambda: broken, context).__enter__()
    assert broken.closed

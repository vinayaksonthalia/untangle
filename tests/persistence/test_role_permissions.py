"""Explicit financial-run role matrix tests."""

import pytest

from persistence.context import Role, TenantContext, TenantContextError


def context(role: Role) -> TenantContext:
    return TenantContext(organisation_id=1, principal_id=1, role=role)


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.OPERATOR])
def test_run_operators_can_create_complete_and_fail(role: Role) -> None:
    ctx = context(role)
    for action in ("create", "complete", "fail"):
        ctx.require_run_mutation(action)


def test_admin_and_owner_can_delete_but_operator_cannot() -> None:
    for role in (Role.OWNER, Role.ADMIN):
        context(role).require_run_mutation("delete")
    with pytest.raises(PermissionError):
        context(Role.OPERATOR).require_run_mutation("delete")


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.AUDITOR])
def test_reviewer_and_auditor_are_read_only_for_runs(role: Role) -> None:
    ctx = context(role)
    for action in ("create", "complete", "fail", "delete"):
        with pytest.raises(PermissionError):
            ctx.require_run_mutation(action)


def test_unknown_run_mutation_fails_closed() -> None:
    with pytest.raises(TenantContextError):
        context(Role.ADMIN).require_run_mutation("approve")

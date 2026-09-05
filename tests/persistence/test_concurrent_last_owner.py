"""Tests proving that the last active owner cannot be demoted or removed, and self-mutation is forbidden."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from auth.service import ControlPlaneService
from auth.sessions import create_session
from persistence.context import Role, TenantContext
from persistence.repositories.control_plane import create_membership, create_principal


def test_users_cannot_modify_own_membership(
    session: Session,
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    # Attempt self-demotion or self-modification
    with pytest.raises(Exception, match="(?i)cannot modify their own membership"):
        ControlPlaneService.mutate_membership(
            session,
            raw_session_token=raw_token,
            target_principal_id=ctx.principal_id,
            new_role_code="admin",
            new_status="active",
        )


def test_two_owners_mutation_and_last_owner_protection(
    session: Session,
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    alice_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    # Add Bob as a second owner
    bob = create_principal(session, "bob.coowner@alpha.test", "Bob Co-Owner")
    create_membership(session, org_id, bob.id, Role.OWNER)
    session.commit()

    bob_token, _ = create_session(session, principal_id=bob.id, active_org_id=org_id)

    # 1. Alice demoting Bob to admin succeeds because Alice remains an active owner
    mem_id, role, status, ver = ControlPlaneService.mutate_membership(
        session,
        raw_session_token=alice_token,
        target_principal_id=bob.id,
        new_role_code="admin",
        new_status="active",
    )
    assert role == "admin"

    # 2. Bob's previous session is now stale due to auth_version bump
    with pytest.raises(Exception, match="(?i)membership modified|unauthorized|stale"):
        ControlPlaneService.mutate_membership(
            session,
            raw_session_token=bob_token,
            target_principal_id=ctx.principal_id,
            new_role_code="admin",
            new_status="active",
        )

    # 3. Bob obtains a new session with his new role (admin)
    bob_admin_token, _ = create_session(session, principal_id=bob.id, active_org_id=org_id)

    # Bob (now admin) attempting to modify Alice (owner) is rejected
    with pytest.raises(Exception, match="(?i)cannot assign or modify owner|admin cannot|forbidden"):
        ControlPlaneService.mutate_membership(
            session,
            raw_session_token=bob_admin_token,
            target_principal_id=ctx.principal_id,
            new_role_code="admin",
            new_status="active",
        )

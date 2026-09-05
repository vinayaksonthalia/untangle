"""Tests for single-use organisation invitations and acceptance binding."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from auth.service import ControlPlaneService
from auth.sessions import create_session
from persistence.context import Role, TenantContext
from persistence.models import OrganisationInvitation, Principal


def test_invitation_lifecycle(
    session: Session,
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    # 1. Create invitation
    raw_inv_token, inv_pub_id, email = ControlPlaneService.create_invitation(
        session,
        raw_session_token=raw_token,
        email="invited.user@example.com",
        role_code=Role.REVIEWER.value,
    )
    assert raw_inv_token is not None
    assert len(raw_inv_token) >= 32
    assert inv_pub_id.startswith("ivt_")
    assert email == "invited.user@example.com"

    # Verify database state
    db_inv = session.query(OrganisationInvitation).filter_by(public_id=inv_pub_id).first()
    assert db_inv is not None
    assert db_inv.status == "pending"
    assert db_inv.role_code == Role.REVIEWER.value

    # 2. Lookup invitation
    details = ControlPlaneService.lookup_invitation(session, raw_inv_token)
    assert details is not None
    assert details.invitation_public_id == inv_pub_id
    assert details.email == "invited.user@example.com"
    assert details.role_code == Role.REVIEWER.value
    assert details.status == "pending"
    assert not details.is_expired

    # 3. Create principal with matching email to accept
    from persistence.ids import PREFIX_PRINCIPAL, generate_public_id

    invited_p = Principal(
        public_id=generate_public_id(PREFIX_PRINCIPAL),
        email="invited.user@example.com",
        display_name="Invited User",
        is_active=True,
    )
    session.add(invited_p)
    session.commit()

    # Create session for invited user (no active org yet)
    invited_sess_token, _ = create_session(session, principal_id=invited_p.id, active_org_id=None)

    # 4. Accept invitation
    mem_id, accepted_org_id, role = ControlPlaneService.accept_invitation(
        session,
        raw_session_token=invited_sess_token,
        raw_invitation_token=raw_inv_token,
    )
    assert mem_id > 0
    assert accepted_org_id == org_id
    assert role == Role.REVIEWER.value

    # Verification: invitation is now accepted, cannot be re-accepted
    session.refresh(db_inv)
    assert db_inv.status == "accepted"

    with pytest.raises((ValueError, RuntimeError), match="(pending|accepted)"):
        ControlPlaneService.accept_invitation(
            session,
            raw_session_token=invited_sess_token,
            raw_invitation_token=raw_inv_token,
        )


def test_invitation_email_mismatch_rejected(
    session: Session,
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    raw_inv_token, _, _ = ControlPlaneService.create_invitation(
        session,
        raw_session_token=raw_token,
        email="targeted@example.com",
        role_code=Role.OPERATOR.value,
    )

    # Create principal with different email
    from persistence.ids import PREFIX_PRINCIPAL, generate_public_id

    attacker = Principal(
        public_id=generate_public_id(PREFIX_PRINCIPAL),
        email="attacker@evil.com",
        display_name="Attacker",
        is_active=True,
    )
    session.add(attacker)
    session.commit()

    attacker_sess_token, _ = create_session(session, principal_id=attacker.id, active_org_id=None)

    # Acceptance must fail with email mismatch
    with pytest.raises((ValueError, RuntimeError), match="email does not match"):
        ControlPlaneService.accept_invitation(
            session,
            raw_session_token=attacker_sess_token,
            raw_invitation_token=raw_inv_token,
        )


def test_invitation_revocation(
    session: Session,
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    raw_inv_token, inv_pub_id, _ = ControlPlaneService.create_invitation(
        session,
        raw_session_token=raw_token,
        email="cancel.me@example.com",
        role_code=Role.AUDITOR.value,
    )

    # Revoke invitation
    revoked = ControlPlaneService.revoke_invitation(
        session,
        raw_session_token=raw_token,
        invitation_public_id=inv_pub_id,
    )
    assert revoked is True

    # Lookup confirms revoked
    details = ControlPlaneService.lookup_invitation(session, raw_inv_token)
    assert details is not None
    assert details.status == "revoked"

"""Tests for data retention purge and redaction maintenance operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.ids import (
    PREFIX_ORGANISATION,
    PREFIX_PRINCIPAL,
    generate_public_id,
)
from persistence.maintenance import run_maintenance_purge
from persistence.models import (
    ControlPlaneSecurityEvent,
    OidcAuthTransaction,
    Organisation,
    OrganisationInvitation,
    Principal,
    UserSession,
)


def _seed_org_and_principal(session: Session) -> tuple[int, int]:
    org = Organisation(
        public_id=generate_public_id(PREFIX_ORGANISATION),
        name="Maintenance Org",
        is_active=True,
    )
    session.add(org)
    principal = Principal(
        public_id=generate_public_id(PREFIX_PRINCIPAL),
        email=f"maint_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Maintenance User",
        is_active=True,
    )
    session.add(principal)
    session.flush()
    return org.id, principal.id


@pytest.mark.parametrize("field", ["sessions_days", "invites_days", "sec_events_days"])
@pytest.mark.parametrize("value", [0, -1, 3651])
def test_maintenance_rejects_invalid_day_retention(session: Session, field: str, value: int):
    with pytest.raises(ValueError):
        run_maintenance_purge(session, **{field: value})


@pytest.mark.parametrize("value", [0, -1, 87601])
def test_maintenance_rejects_invalid_oidc_retention(session: Session, value: int):
    with pytest.raises(ValueError):
        run_maintenance_purge(session, oidc_hours=value)


def test_maintenance_purge_security_events(session: Session) -> None:
    now = datetime.now(UTC)
    old_event = ControlPlaneSecurityEvent(
        public_id=f"sec_{uuid.uuid4().hex[:16]}",
        event_type="auth.oidc.initiated",
        subject_type="ip",
        subject_identifier="127.0.0.1",
        ip_hash="0" * 64,
        details_json={},
        created_at=now - timedelta(days=95),
    )
    recent_event = ControlPlaneSecurityEvent(
        public_id=f"sec_{uuid.uuid4().hex[:16]}",
        event_type="auth.oidc.initiated",
        subject_type="ip",
        subject_identifier="127.0.0.1",
        ip_hash="0" * 64,
        details_json={},
        created_at=now - timedelta(days=10),
    )
    session.add_all([old_event, recent_event])
    session.commit()

    results = run_maintenance_purge(session, sec_events_days=90)
    assert results["security_events_purged"] >= 1

    remaining_old = session.scalar(
        select(ControlPlaneSecurityEvent).where(
            ControlPlaneSecurityEvent.public_id == old_event.public_id
        )
    )
    assert remaining_old is None

    remaining_recent = session.scalar(
        select(ControlPlaneSecurityEvent).where(
            ControlPlaneSecurityEvent.public_id == recent_event.public_id
        )
    )
    assert remaining_recent is not None


def test_maintenance_purge_oidc_transactions(session: Session) -> None:
    now = datetime.now(UTC)
    old_tx = OidcAuthTransaction(
        public_id=f"tx_{uuid.uuid4().hex[:16]}",
        state_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        nonce_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        code_verifier_encrypted="enc_old",
        return_to="/app",
        expires_at=now - timedelta(hours=2),
        consumed_at=None,
        created_at=now - timedelta(hours=3),
    )
    consumed_tx = OidcAuthTransaction(
        public_id=f"tx_{uuid.uuid4().hex[:16]}",
        state_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        nonce_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        code_verifier_encrypted="enc_cons",
        return_to="/app",
        expires_at=now + timedelta(hours=1),
        consumed_at=now - timedelta(minutes=10),
        created_at=now - timedelta(minutes=15),
    )
    fresh_tx = OidcAuthTransaction(
        public_id=f"tx_{uuid.uuid4().hex[:16]}",
        state_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        nonce_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        code_verifier_encrypted="enc_fresh",
        return_to="/app",
        expires_at=now + timedelta(hours=1),
        consumed_at=None,
        created_at=now - timedelta(minutes=5),
    )
    session.add_all([old_tx, consumed_tx, fresh_tx])
    session.commit()

    results = run_maintenance_purge(session, oidc_hours=1)
    assert results["oidc_transactions_purged"] >= 2

    assert (
        session.scalar(
            select(OidcAuthTransaction).where(OidcAuthTransaction.public_id == old_tx.public_id)
        )
        is None
    )
    assert (
        session.scalar(
            select(OidcAuthTransaction).where(
                OidcAuthTransaction.public_id == consumed_tx.public_id
            )
        )
        is None
    )
    assert (
        session.scalar(
            select(OidcAuthTransaction).where(OidcAuthTransaction.public_id == fresh_tx.public_id)
        )
        is not None
    )


def test_maintenance_purge_expired_sessions(session: Session) -> None:
    now = datetime.now(UTC)
    org_id, principal_id = _seed_org_and_principal(session)

    old_revoked_sess = UserSession(
        public_id=f"ses_{uuid.uuid4().hex[:16]}",
        principal_id=principal_id,
        session_token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        active_organisation_id=org_id,
        membership_auth_version=1,
        ip_hash="0" * 64,
        last_active_at=now - timedelta(days=40),
        idle_expires_at=now - timedelta(days=40),
        absolute_expires_at=now - timedelta(days=39),
        revoked_at=now - timedelta(days=35),
        created_at=now - timedelta(days=40),
    )
    active_sess = UserSession(
        public_id=f"ses_{uuid.uuid4().hex[:16]}",
        principal_id=principal_id,
        session_token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        active_organisation_id=org_id,
        membership_auth_version=1,
        ip_hash="0" * 64,
        last_active_at=now,
        idle_expires_at=now + timedelta(minutes=30),
        absolute_expires_at=now + timedelta(hours=12),
        created_at=now,
    )
    session.add_all([old_revoked_sess, active_sess])
    session.commit()

    results = run_maintenance_purge(session, sessions_days=30)
    assert results["sessions_purged"] >= 1

    assert (
        session.scalar(
            select(UserSession).where(UserSession.public_id == old_revoked_sess.public_id)
        )
        is None
    )
    assert (
        session.scalar(select(UserSession).where(UserSession.public_id == active_sess.public_id))
        is not None
    )


def test_maintenance_redact_invitations(session: Session) -> None:
    now = datetime.now(UTC)
    org_id, principal_id = _seed_org_and_principal(session)

    old_accepted_inv = OrganisationInvitation(
        public_id=f"inv_{uuid.uuid4().hex[:16]}",
        organisation_id=org_id,
        invited_by_principal_id=principal_id,
        email="accepted_old@example.com",
        role_code="reviewer",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status="accepted",
        expires_at=now - timedelta(days=10),
        accepted_at=now - timedelta(days=16),
        created_at=now - timedelta(days=20),
    )
    recent_accepted_inv = OrganisationInvitation(
        public_id=f"inv_{uuid.uuid4().hex[:16]}",
        organisation_id=org_id,
        invited_by_principal_id=principal_id,
        email="accepted_recent@example.com",
        role_code="reviewer",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status="accepted",
        expires_at=now + timedelta(days=2),
        accepted_at=now - timedelta(days=2),
        created_at=now - timedelta(days=3),
    )
    session.add_all([old_accepted_inv, recent_accepted_inv])
    session.commit()

    results = run_maintenance_purge(session, invites_days=14)
    assert results["invitations_redacted"] >= 1

    # Redaction runs server-side via raw SQL; expire the identity map so the
    # ORM re-reads the redacted rows instead of returning cached instances
    # (the factory uses expire_on_commit=False).
    session.expire_all()

    inv1 = session.scalar(
        select(OrganisationInvitation).where(
            OrganisationInvitation.public_id == old_accepted_inv.public_id
        )
    )
    assert inv1 is not None
    assert inv1.email == "redacted@untangle.internal"

    inv2 = session.scalar(
        select(OrganisationInvitation).where(
            OrganisationInvitation.public_id == recent_accepted_inv.public_id
        )
    )
    assert inv2 is not None
    assert inv2.email == "accepted_recent@example.com"

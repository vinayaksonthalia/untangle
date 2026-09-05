"""Tests for idle expiry, absolute expiry, and stale session revocation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from auth.crypto import hash_token
from auth.sessions import create_session, lookup_session, revoke_all_sessions
from persistence.context import TenantContext
from persistence.models import OrganisationMembership, UserSession


def test_session_idle_expiry(session: Session, tenant_a: tuple[TenantContext, int]) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)

    # Set timestamps simulating 35 minutes of inactivity (created 40m ago, last active 35m ago, idle 5m ago)
    db_sess = session.query(UserSession).filter_by(session_token_hash=token_hash).first()
    assert db_sess is not None
    now = datetime.now(UTC)
    db_sess.created_at = now - timedelta(minutes=40)
    db_sess.last_active_at = now - timedelta(minutes=35)
    db_sess.idle_expires_at = now - timedelta(minutes=5)
    session.commit()

    info = lookup_session(session, raw_token)
    assert info is not None
    assert info.is_revoked is True


def test_session_absolute_expiry(session: Session, tenant_a: tuple[TenantContext, int]) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)

    # Set timestamps simulating 12h5m total age (created 12h5m ago, absolute expiry 5m ago)
    db_sess = session.query(UserSession).filter_by(session_token_hash=token_hash).first()
    assert db_sess is not None
    now = datetime.now(UTC)
    db_sess.created_at = now - timedelta(hours=12, minutes=5)
    db_sess.last_active_at = now - timedelta(hours=1)
    db_sess.idle_expires_at = now - timedelta(minutes=5)
    db_sess.absolute_expires_at = now - timedelta(minutes=5)
    session.commit()

    info = lookup_session(session, raw_token)
    assert info is not None
    assert info.is_revoked is True


def test_membership_auth_version_bump_marks_session_stale(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    # Session was created when membership auth_version was 1
    info = lookup_session(session, raw_token)
    assert info is not None
    assert not info.is_stale

    # Bump membership auth_version (e.g. from role mutation or permission change)
    mem = (
        session.query(OrganisationMembership)
        .filter_by(organisation_id=org_id, principal_id=ctx.principal_id)
        .first()
    )
    assert mem is not None
    mem.auth_version += 1
    session.commit()

    # Next lookup must detect stale version mismatch
    info_after = lookup_session(session, raw_token)
    assert info_after is not None
    assert info_after.is_stale is True


def test_revoke_all_sessions(session: Session, tenant_a: tuple[TenantContext, int]) -> None:
    ctx, org_id = tenant_a
    raw_t1, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    raw_t2, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    raw_t3, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    revoked_count = revoke_all_sessions(session, raw_t1)
    assert revoked_count >= 3

    for token in (raw_t1, raw_t2, raw_t3):
        info = lookup_session(session, token)
        assert info is not None
        assert info.is_revoked is True

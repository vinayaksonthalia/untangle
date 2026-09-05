"""Tests for session creation, sliding idle touch, revocation, and org switching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from auth.crypto import hash_token
from auth.sessions import (
    _ensure_utc,
    create_session,
    lookup_session,
    revoke_session,
    switch_organisation,
    touch_session,
    touch_session_throttled,
)
from persistence.context import Role, TenantContext
from persistence.models import UserSession


def test_session_creation_and_lookup(session: Session, tenant_a: tuple[TenantContext, int]) -> None:
    ctx, org_id = tenant_a
    raw_token, session_info = create_session(
        session,
        principal_id=ctx.principal_id,
        active_org_id=org_id,
        ip_address="127.0.0.1",
        user_agent="LifecycleTest/1.0",
    )
    assert raw_token is not None
    assert len(raw_token) >= 32
    assert session_info.principal_id == ctx.principal_id
    assert session_info.active_organisation_id == org_id
    assert session_info.active_role_code == Role.OWNER.value

    # Direct database verification
    token_hash = hash_token(raw_token)
    db_sess = session.query(UserSession).filter_by(session_token_hash=token_hash).first()
    assert db_sess is not None
    # Invariant: last_active_at <= idle_expires_at <= absolute_expires_at
    assert (
        _ensure_utc(db_sess.last_active_at)
        <= _ensure_utc(db_sess.idle_expires_at)
        <= _ensure_utc(db_sess.absolute_expires_at)
    )

    # Lookup by raw token
    looked_up = lookup_session(session, raw_token)
    assert looked_up is not None
    assert looked_up.public_id == session_info.public_id
    assert looked_up.principal_id == ctx.principal_id
    assert looked_up.active_organisation_id == org_id
    assert not looked_up.is_stale
    assert not looked_up.is_revoked


def test_session_sliding_idle_touch_capped_at_absolute_expiry(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)

    # Simulate session nearing 12-hour limit (created 11h50m ago, so 10m left until absolute expiry)
    db_sess = session.query(UserSession).filter_by(session_token_hash=token_hash).first()
    assert db_sess is not None
    now = datetime.now(UTC)
    db_sess.created_at = now - timedelta(hours=11, minutes=50)
    db_sess.absolute_expires_at = now + timedelta(minutes=10)
    db_sess.idle_expires_at = now + timedelta(minutes=5)
    db_sess.last_active_at = now - timedelta(minutes=10)
    session.commit()

    # Touch session: 30 minutes idle would overshoot abs_exp (now + 10m), so it MUST cap at abs_exp
    touched = touch_session(session, raw_token)
    assert touched is True

    session.refresh(db_sess)
    assert _ensure_utc(db_sess.idle_expires_at) <= _ensure_utc(db_sess.absolute_expires_at)
    assert _ensure_utc(db_sess.idle_expires_at) == _ensure_utc(db_sess.absolute_expires_at)


def test_session_touch_throttled_skips_recent_writes(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)

    # Immediately touching again within 60s should be throttled (no-op)
    touched = touch_session_throttled(session, raw_token, throttle_seconds=60)
    assert touched is False

    # Force last_active_at to 120 seconds ago
    db_sess = session.query(UserSession).filter_by(session_token_hash=token_hash).first()
    assert db_sess is not None
    db_sess.last_active_at = datetime.now(UTC) - timedelta(seconds=120)
    session.commit()

    # Now throttled touch should execute
    touched_after = touch_session_throttled(session, raw_token, throttle_seconds=60)
    assert touched_after is True


def test_session_revocation(session: Session, tenant_a: tuple[TenantContext, int]) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    revoked = revoke_session(session, raw_token)
    assert revoked is True

    # Lookup reflects revocation
    looked_up = lookup_session(session, raw_token)
    assert looked_up is not None
    assert looked_up.is_revoked is True


def test_switch_organisation_rotates_token_and_updates_role(
    session: Session,
    tenant_a: tuple[TenantContext, int],
    tenant_b: tuple[TenantContext, int],
) -> None:
    ctx_a, org_a_id = tenant_a
    _, org_b_id = tenant_b

    # Add Alice to Organisation B as REVIEWER
    from persistence.repositories.control_plane import create_membership

    create_membership(session, org_b_id, ctx_a.principal_id, Role.REVIEWER)
    session.commit()

    # Alice creates session initially in Org A (OWNER)
    old_raw_token, session_info = create_session(
        session, principal_id=ctx_a.principal_id, active_org_id=org_a_id
    )
    assert session_info.active_role_code == Role.OWNER.value

    # Switch to Org B
    new_raw_token, new_auth_ver, new_role = switch_organisation(
        session, old_raw_token, target_org_id=org_b_id
    )

    # Token must rotate
    assert new_raw_token != old_raw_token
    assert new_role == Role.REVIEWER.value

    # Old token lookup indicates revoked or non-existent
    old_lookup = lookup_session(session, old_raw_token)
    assert old_lookup is None or old_lookup.is_revoked is True

    # New token resolves Org B and REVIEWER role
    new_lookup = lookup_session(session, new_raw_token)
    assert new_lookup is not None
    assert new_lookup.active_organisation_id == org_b_id
    assert new_lookup.active_role_code == Role.REVIEWER.value

"""Session management, token generation, sliding expiry, and revocation.

Strictly enforces:
- 30-minute sliding idle window capped at 12-hour absolute expiry (idle <= absolute).
- SHA-256 session token hashing (zero raw token storage).
- Throttled database activity touches (60-second minimum touch interval).
- Stale session detection via membership auth_version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from auth.audit import record_security_event
from auth.crypto import (
    generate_session_token,
    hash_ip,
    hash_token,
    truncate_user_agent,
)
from persistence.ids import (
    PREFIX_AUDIT_EVENT,
    PREFIX_SESSION,
    generate_public_id,
)
from persistence.models import Organisation, OrganisationMembership, Principal, UserSession

IDLE_TIMEOUT_SECONDS: Final[int] = 1800  # 30 minutes
ABSOLUTE_TIMEOUT_SECONDS: Final[int] = 43200  # 12 hours
TOUCH_THROTTLE_SECONDS: Final[int] = 60  # 1 minute throttle


def _ensure_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class SessionInfo:
    """Authoritative resolved session state."""

    session_id: int
    public_id: str
    principal_id: int
    principal_public_id: str
    principal_email: str
    principal_display_name: str
    active_organisation_id: int | None
    active_org_public_id: str | None
    active_role_code: str | None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    last_active_at: datetime
    is_revoked: bool
    is_stale: bool


def create_session(
    auth_session: Session,
    principal_id: int,
    active_org_id: int | None = None,
    ip_address: str = "127.0.0.1",
    user_agent: str | None = None,
) -> tuple[str, SessionInfo]:
    """Create a new user session using privileged untangle_auth connection.

    Returns:
        tuple[str, SessionInfo]: (raw_session_token, session_info)
    """
    raw_token = generate_session_token()
    token_hash = hash_token(raw_token)
    public_id = generate_public_id(PREFIX_SESSION)
    now = datetime.now(UTC)
    idle_exp = now + timedelta(seconds=IDLE_TIMEOUT_SECONDS)
    abs_exp = now + timedelta(seconds=ABSOLUTE_TIMEOUT_SECONDS)
    ip_h = hash_ip(ip_address)
    ua_trunc = truncate_user_agent(user_agent)

    bind = auth_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        row = auth_session.execute(
            text(
                """
                SELECT session_id, session_public_id
                FROM public.fn_auth_create_session(
                    :public_id, :principal_id, :token_hash, :active_org_id,
                    :ip_hash, :user_agent_truncated, :idle_exp, :abs_exp
                )
                """
            ),
            {
                "public_id": public_id,
                "principal_id": principal_id,
                "token_hash": token_hash,
                "active_org_id": active_org_id,
                "ip_hash": ip_h,
                "user_agent_truncated": ua_trunc,
                "idle_exp": idle_exp,
                "abs_exp": abs_exp,
            },
        ).first()
        if not row:
            raise RuntimeError("Failed to create session via fn_auth_create_session")
    else:
        # SQLite fallback
        auth_version = None
        if active_org_id is not None:
            mem = auth_session.scalar(
                select(OrganisationMembership).where(
                    OrganisationMembership.organisation_id == active_org_id,
                    OrganisationMembership.principal_id == principal_id,
                    OrganisationMembership.status == "active",
                )
            )
            if not mem:
                raise RuntimeError(f"No active membership in organisation {active_org_id}")
            auth_version = mem.auth_version

        sess = UserSession(
            public_id=public_id,
            principal_id=principal_id,
            session_token_hash=token_hash,
            active_organisation_id=active_org_id,
            membership_auth_version=auth_version,
            ip_hash=ip_h,
            user_agent_truncated=ua_trunc,
            last_active_at=now,
            idle_expires_at=idle_exp,
            absolute_expires_at=abs_exp,
        )
        auth_session.add(sess)
        auth_session.flush()

    record_security_event(
        auth_session,
        event_type="auth.session.created",
        subject_type="user_session",
        subject_identifier=public_id,
        ip_hash=ip_h,
        user_agent_truncated=ua_trunc,
        actor_principal_id=principal_id,
        details={"active_org_id": active_org_id},
    )
    auth_session.commit()

    # Resolve full SessionInfo
    info = lookup_session(auth_session, raw_token)
    if not info:
        raise RuntimeError("Newly created session could not be looked up")
    return raw_token, info


def lookup_session(app_session: Session, raw_token: str) -> SessionInfo | None:
    """Lookup session state via untangle_app connection.

    Derived authority: resolves principal and active role internally from session_token_hash.
    """
    token_hash = hash_token(raw_token)
    bind = app_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        row = app_session.execute(
            text(
                """
                SELECT session_id, session_public_id, principal_id, principal_public_id,
                       principal_email, principal_display_name, active_organisation_id,
                       active_org_public_id, active_role_code, idle_expires_at,
                       absolute_expires_at, last_active_at, is_revoked, is_stale
                FROM public.fn_auth_lookup_session(:token_hash)
                """
            ),
            {"token_hash": token_hash},
        ).first()
        if not row:
            return None
        return SessionInfo(
            session_id=row.session_id,
            public_id=row.session_public_id,
            principal_id=row.principal_id,
            principal_public_id=row.principal_public_id,
            principal_email=row.principal_email,
            principal_display_name=row.principal_display_name,
            active_organisation_id=row.active_organisation_id,
            active_org_public_id=row.active_org_public_id,
            active_role_code=row.active_role_code,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
            last_active_at=row.last_active_at,
            is_revoked=row.is_revoked,
            is_stale=row.is_stale,
        )

    # SQLite fallback
    s = app_session.scalar(select(UserSession).where(UserSession.session_token_hash == token_hash))
    if not s:
        return None

    p = app_session.scalar(select(Principal).where(Principal.id == s.principal_id))
    if not p:
        return None

    now = datetime.now(UTC)
    is_revoked = bool(
        s.revoked_at is not None
        or now >= _ensure_utc(s.absolute_expires_at)
        or now >= _ensure_utc(s.idle_expires_at)
        or not p.is_active
    )

    active_org_pub_id = None
    active_role_code = None
    is_stale = False

    if s.active_organisation_id is not None:
        o = app_session.scalar(
            select(Organisation).where(Organisation.id == s.active_organisation_id)
        )
        mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == s.active_organisation_id,
                OrganisationMembership.principal_id == s.principal_id,
            )
        )
        if not o or not o.is_active or not mem or mem.status != "active":
            is_stale = True
        elif mem.auth_version != s.membership_auth_version:
            is_stale = True
        else:
            active_org_pub_id = o.public_id
            active_role_code = mem.role_code

    return SessionInfo(
        session_id=s.id,
        public_id=s.public_id,
        principal_id=p.id,
        principal_public_id=p.public_id,
        principal_email=p.email,
        principal_display_name=p.display_name,
        active_organisation_id=s.active_organisation_id,
        active_org_public_id=active_org_pub_id,
        active_role_code=active_role_code,
        idle_expires_at=s.idle_expires_at,
        absolute_expires_at=s.absolute_expires_at,
        last_active_at=s.last_active_at,
        is_revoked=is_revoked,
        is_stale=is_stale,
    )


def touch_session_throttled(
    app_session: Session,
    raw_token: str,
    idle_window_seconds: int = IDLE_TIMEOUT_SECONDS,
    throttle_seconds: int = TOUCH_THROTTLE_SECONDS,
) -> bool:
    """Touch session activity timestamp with write throttling."""
    token_hash = hash_token(raw_token)
    bind = app_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = app_session.execute(
            text(
                """
                SELECT public.fn_auth_touch_session_throttled(
                    :token_hash, :idle_window_seconds, :throttle_seconds
                )
                """
            ),
            {
                "token_hash": token_hash,
                "idle_window_seconds": idle_window_seconds,
                "throttle_seconds": throttle_seconds,
            },
        ).scalar()
        app_session.commit()
        return bool(res)
    else:
        now = datetime.now(UTC)
        s = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
                UserSession.last_active_at <= now - timedelta(seconds=throttle_seconds),
            )
        )
        updated = False
        if s:
            s.last_active_at = now
            s.idle_expires_at = min(
                now + timedelta(seconds=idle_window_seconds), _ensure_utc(s.absolute_expires_at)
            )
            updated = True
        app_session.commit()
        return updated


def touch_session(
    app_session: Session,
    raw_token: str,
    idle_window_seconds: int = IDLE_TIMEOUT_SECONDS,
) -> bool:
    """Unconditionally touch session without write throttling (throttle_seconds=0)."""
    return touch_session_throttled(
        app_session, raw_token, idle_window_seconds=idle_window_seconds, throttle_seconds=0
    )


def revoke_session(
    app_session: Session,
    raw_token: str,
    ip_address: str = "127.0.0.1",
    user_agent: str | None = None,
) -> bool:
    """Revoke a single session token."""
    token_hash = hash_token(raw_token)
    bind = app_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        res = app_session.execute(
            text("SELECT public.fn_auth_revoke_session(:token_hash)"),
            {"token_hash": token_hash},
        ).scalar()
        revoked = bool(res)
    else:
        s = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
            )
        )
        if s:
            s.revoked_at = datetime.now(UTC)
            revoked = True
        else:
            revoked = False

    if revoked:
        record_security_event(
            app_session,
            event_type="auth.session.revoked",
            subject_type="user_session",
            subject_identifier=token_hash[:16],
            ip_hash=hash_ip(ip_address),
            user_agent_truncated=truncate_user_agent(user_agent),
            details={"scope": "single_session"},
        )
    app_session.commit()
    return revoked


def revoke_all_sessions(
    app_session: Session,
    raw_token: str,
    ip_address: str = "127.0.0.1",
    user_agent: str | None = None,
) -> int:
    """Revoke all active sessions for the principal derived from this session."""
    token_hash = hash_token(raw_token)
    bind = app_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        count = (
            app_session.execute(
                text("SELECT public.fn_auth_revoke_all_sessions(:token_hash)"),
                {"token_hash": token_hash},
            ).scalar()
            or 0
        )
    else:
        now = datetime.now(UTC)
        s = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not s:
            return 0
        all_s = app_session.scalars(
            select(UserSession).where(
                UserSession.principal_id == s.principal_id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for sess in all_s:
            sess.revoked_at = now
        count = len(all_s)

    if count > 0:
        record_security_event(
            app_session,
            event_type="auth.session.revoked",
            subject_type="user_session",
            subject_identifier=token_hash[:16],
            ip_hash=hash_ip(ip_address),
            user_agent_truncated=truncate_user_agent(user_agent),
            details={"scope": "all_sessions", "count": count},
        )
    app_session.commit()
    return count


def switch_organisation(
    app_session: Session,
    raw_token: str,
    target_org_id: int,
) -> tuple[str, int, str]:
    """Switch active organisation for the session, rotating the session token.

    Returns:
        tuple[str, int, str]: (new_raw_token, new_auth_version, role_code)
    """
    token_hash = hash_token(raw_token)
    new_raw_token = generate_session_token()
    new_token_hash = hash_token(new_raw_token)
    now = datetime.now(UTC)
    new_idle_exp = now + timedelta(seconds=IDLE_TIMEOUT_SECONDS)
    abs_exp = now + timedelta(seconds=ABSOLUTE_TIMEOUT_SECONDS)
    audit_public_id = generate_public_id(PREFIX_AUDIT_EVENT)

    bind = app_session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        row = app_session.execute(
            text(
                """
                SELECT new_auth_version, role_code
                FROM public.fn_auth_switch_organisation(
                    :token_hash, :target_org_id, :new_token_hash,
                    :idle_exp, :abs_exp, :audit_public_id
                )
                """
            ),
            {
                "token_hash": token_hash,
                "target_org_id": target_org_id,
                "new_token_hash": new_token_hash,
                "idle_exp": new_idle_exp,
                "abs_exp": abs_exp,
                "audit_public_id": audit_public_id,
            },
        ).first()
        if not row:
            raise RuntimeError("Failed to switch organisation via fn_auth_switch_organisation")
        auth_version = row.new_auth_version
        role_code = row.role_code
    else:
        # SQLite fallback
        s = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not s:
            raise RuntimeError("Unauthorized: invalid or expired session")

        o = app_session.scalar(
            select(Organisation).where(
                Organisation.id == target_org_id,
                Organisation.is_active.is_(True),
            )
        )
        mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == target_org_id,
                OrganisationMembership.principal_id == s.principal_id,
                OrganisationMembership.status == "active",
            )
        )
        if not o or not mem:
            raise RuntimeError("Target organisation not found or no active membership")

        s.active_organisation_id = target_org_id
        s.membership_auth_version = mem.auth_version
        s.session_token_hash = new_token_hash
        s.last_active_at = now
        s.idle_expires_at = min(new_idle_exp, _ensure_utc(s.absolute_expires_at))
        auth_version = mem.auth_version
        role_code = mem.role_code

    app_session.commit()
    return new_raw_token, auth_version, role_code

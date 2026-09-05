"""Authoritative control-plane service for organisations, memberships, and invitations.

Enforces zero caller-supplied identity: all operations accept raw session token,
deriving actor identity, permissions, and organization context internally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from auth.crypto import (
    generate_invitation_token,
    hash_token,
)
from auth.sessions import _ensure_utc
from persistence.ids import (
    PREFIX_AUDIT_EVENT,
    PREFIX_INVITATION,
    PREFIX_MEMBERSHIP,
    PREFIX_ORGANISATION,
    generate_public_id,
)
from persistence.models import (
    AuditEvent,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    Principal,
    UserSession,
)

INVITATION_TTL_DAYS = 7


def _exec_control_plane_fn(app_session: Session, sql: str, params: dict):
    """Execute a SECURITY DEFINER control-plane function and normalise errors.

    The control-plane SQL functions signal business-rule violations with
    ``RAISE EXCEPTION`` (invalid session, forbidden role, stale membership,
    last-owner protection, ...). These reach SQLAlchemy as an opaque
    ``DBAPIError`` and, once raised, poison the current transaction so any
    further statement fails with "current transaction is aborted". To give
    callers the same plaintext ``RuntimeError`` contract as the SQLite
    fallbacks — and to leave the session usable — translate the driver's
    primary message and roll back before re-raising.
    """
    try:
        return app_session.execute(text(sql), params).first()
    except DBAPIError as exc:
        app_session.rollback()
        message = None
        diag = getattr(getattr(exc, "orig", None), "diag", None)
        if diag is not None:
            message = getattr(diag, "message_primary", None)
        raise RuntimeError(message or "Control-plane operation failed") from exc


@dataclass(frozen=True)
class OrgListItem:
    org_id: int
    org_public_id: str
    org_name: str
    role_code: str
    membership_status: str


@dataclass(frozen=True)
class MemberListItem:
    membership_public_id: str
    principal_public_id: str
    email: str
    display_name: str
    role_code: str
    status: str
    auth_version: int
    created_at: datetime


@dataclass(frozen=True)
class InvitationListItem:
    invitation_public_id: str
    email: str
    role_code: str
    status: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class InvitationDetails:
    invitation_id: int
    invitation_public_id: str
    organisation_name: str
    email: str
    role_code: str
    status: str
    is_expired: bool


class ControlPlaneService:
    """Service boundary for authenticated organisation, membership, and invitation actions."""

    @staticmethod
    def create_organisation(
        app_session: Session, raw_session_token: str, name: str
    ) -> tuple[int, str]:
        """Create a new organisation with caller as owner."""
        token_hash = hash_token(raw_session_token)
        org_pub_id = generate_public_id(PREFIX_ORGANISATION)
        mem_pub_id = generate_public_id(PREFIX_MEMBERSHIP)
        audit_1 = generate_public_id(PREFIX_AUDIT_EVENT)
        audit_2 = generate_public_id(PREFIX_AUDIT_EVENT)

        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            row = app_session.execute(
                text(
                    """
                    SELECT org_id, org_public_id
                    FROM public.fn_org_create(
                        :token_hash, :name, :org_pub_id, :mem_pub_id, :audit_1, :audit_2
                    )
                    """
                ),
                {
                    "token_hash": token_hash,
                    "name": name,
                    "org_pub_id": org_pub_id,
                    "mem_pub_id": mem_pub_id,
                    "audit_1": audit_1,
                    "audit_2": audit_2,
                },
            ).first()
            if not row:
                raise RuntimeError("Failed to create organisation via fn_org_create")
            app_session.commit()
            return row.org_id, row.org_public_id

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess:
            raise RuntimeError("Unauthorized: invalid or expired session")

        org = Organisation(public_id=org_pub_id, name=name, is_active=True)
        app_session.add(org)
        app_session.flush()

        mem = OrganisationMembership(
            public_id=mem_pub_id,
            organisation_id=org.id,
            principal_id=sess.principal_id,
            role_code="owner",
            status="active",
            auth_version=1,
        )
        app_session.add(mem)

        # Audit events
        app_session.add(
            AuditEvent(
                public_id=audit_1,
                organisation_id=org.id,
                actor_principal_id=sess.principal_id,
                event_type="organisation.created",
                subject_type="organisation",
                subject_public_id=org_pub_id,
                metadata_json={"name": name},
            )
        )
        app_session.add(
            AuditEvent(
                public_id=audit_2,
                organisation_id=org.id,
                actor_principal_id=sess.principal_id,
                event_type="membership.assigned",
                subject_type="organisation_membership",
                subject_public_id=mem_pub_id,
                metadata_json={"role": "owner"},
            )
        )
        app_session.commit()
        return org.id, org.public_id

    @staticmethod
    def list_organisations(app_session: Session, raw_session_token: str) -> list[OrgListItem]:
        """List all organisations in which the session principal holds membership."""
        token_hash = hash_token(raw_session_token)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            rows = app_session.execute(
                text(
                    """
                    SELECT org_id, org_public_id, org_name, role_code, membership_status
                    FROM public.fn_org_list(:token_hash)
                    """
                ),
                {"token_hash": token_hash},
            ).all()
            return [
                OrgListItem(
                    org_id=r.org_id,
                    org_public_id=r.org_public_id,
                    org_name=r.org_name,
                    role_code=r.role_code,
                    membership_status=r.membership_status,
                )
                for r in rows
            ]

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess:
            return []

        memberships = app_session.scalars(
            select(OrganisationMembership).where(
                OrganisationMembership.principal_id == sess.principal_id
            )
        ).all()
        result = []
        for m in memberships:
            org = app_session.scalar(
                select(Organisation).where(
                    Organisation.id == m.organisation_id,
                    Organisation.is_active.is_(True),
                )
            )
            if org:
                result.append(
                    OrgListItem(
                        org_id=org.id,
                        org_public_id=org.public_id,
                        org_name=org.name,
                        role_code=m.role_code,
                        membership_status=m.status,
                    )
                )
        result.sort(key=lambda x: x.org_name)
        return result

    @staticmethod
    def list_memberships(app_session: Session, raw_session_token: str) -> list[MemberListItem]:
        """List all members of the caller's active organisation."""
        token_hash = hash_token(raw_session_token)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            rows = app_session.execute(
                text(
                    """
                    SELECT membership_public_id, principal_public_id, email, display_name,
                           role_code, status, auth_version, created_at
                    FROM public.fn_membership_list(:token_hash)
                    """
                ),
                {"token_hash": token_hash},
            ).all()
            return [
                MemberListItem(
                    membership_public_id=r.membership_public_id,
                    principal_public_id=r.principal_public_id,
                    email=r.email,
                    display_name=r.display_name,
                    role_code=r.role_code,
                    status=r.status,
                    auth_version=r.auth_version,
                    created_at=r.created_at,
                )
                for r in rows
            ]

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess or sess.active_organisation_id is None:
            raise RuntimeError("Unauthorized: session not found or no active organisation")

        memberships = app_session.scalars(
            select(OrganisationMembership)
            .where(OrganisationMembership.organisation_id == sess.active_organisation_id)
            .order_by(OrganisationMembership.created_at.asc())
        ).all()
        result = []
        for m in memberships:
            p = app_session.scalar(select(Principal).where(Principal.id == m.principal_id))
            if p:
                result.append(
                    MemberListItem(
                        membership_public_id=m.public_id,
                        principal_public_id=p.public_id,
                        email=p.email,
                        display_name=p.display_name,
                        role_code=m.role_code,
                        status=m.status,
                        auth_version=m.auth_version,
                        created_at=m.created_at,
                    )
                )
        return result

    @staticmethod
    def mutate_membership(
        app_session: Session,
        raw_session_token: str,
        target_principal_id: int,
        new_role_code: str,
        new_status: str,
    ) -> tuple[int, str, str, int]:
        """Mutate role or status of an organisation member with mutex lock.

        Returns:
            tuple[int, str, str, int]: (membership_id, updated_role, updated_status, new_auth_version)
        """
        token_hash = hash_token(raw_session_token)
        audit_pub_id = generate_public_id(PREFIX_AUDIT_EVENT)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            row = _exec_control_plane_fn(
                app_session,
                """
                    SELECT membership_id, updated_role, updated_status, new_auth_version
                    FROM public.fn_membership_mutate_with_mutex(
                        :token_hash, :target_principal_id, :new_role_code,
                        :new_status, :audit_pub_id
                    )
                    """,
                {
                    "token_hash": token_hash,
                    "target_principal_id": target_principal_id,
                    "new_role_code": new_role_code,
                    "new_status": new_status,
                    "audit_pub_id": audit_pub_id,
                },
            )
            if not row:
                raise RuntimeError(
                    "Failed to mutate membership via fn_membership_mutate_with_mutex"
                )
            app_session.commit()
            return row.membership_id, row.updated_role, row.updated_status, row.new_auth_version

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess or sess.active_organisation_id is None:
            raise RuntimeError("Unauthorized: session not found or no active organisation")

        org_id = sess.active_organisation_id
        actor_mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == sess.principal_id,
                OrganisationMembership.status == "active",
            )
        )
        if not actor_mem or actor_mem.role_code not in ("owner", "admin"):
            raise RuntimeError("Forbidden: only owners and admins may modify memberships")

        if sess.principal_id == target_principal_id:
            raise RuntimeError("Forbidden: users cannot modify their own membership role or status")

        target_mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == target_principal_id,
            )
        )
        if not target_mem:
            raise RuntimeError("Target member not found in organisation")

        if actor_mem.role_code == "admin" and (
            target_mem.role_code == "owner" or new_role_code == "owner"
        ):
            raise RuntimeError("Forbidden: administrators cannot alter or assign owner roles")

        # Last-owner check
        if (
            target_mem.role_code == "owner"
            and target_mem.status == "active"
            and (new_role_code != "owner" or new_status != "active")
        ):
            active_owners_count = app_session.scalar(
                select(func.count(OrganisationMembership.id)).where(
                    OrganisationMembership.organisation_id == org_id,
                    OrganisationMembership.role_code == "owner",
                    OrganisationMembership.status == "active",
                )
            )
            if active_owners_count <= 1:
                raise RuntimeError(
                    f"Cannot demote or remove the last active owner of organisation {org_id}"
                )

        target_mem.role_code = new_role_code
        target_mem.status = new_status
        target_mem.auth_version += 1

        # Revoke target user's active sessions in this org
        target_sessions = app_session.scalars(
            select(UserSession).where(
                UserSession.principal_id == target_principal_id,
                UserSession.active_organisation_id == org_id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for ts in target_sessions:
            ts.revoked_at = now

        # Record audit event
        ev_type = "membership.suspended" if new_status != "active" else "membership.role_changed"
        app_session.add(
            AuditEvent(
                public_id=audit_pub_id,
                organisation_id=org_id,
                actor_principal_id=sess.principal_id,
                event_type=ev_type,
                subject_type="organisation_membership",
                subject_public_id=target_mem.public_id,
                metadata_json={
                    "target_principal_id": target_principal_id,
                    "new_role": new_role_code,
                },
            )
        )
        app_session.commit()
        return target_mem.id, new_role_code, new_status, target_mem.auth_version

    @staticmethod
    def create_invitation(
        app_session: Session,
        raw_session_token: str,
        email: str,
        role_code: str,
    ) -> tuple[str, str, str]:
        """Create a single-use organisation invitation.

        Returns:
            tuple[str, str, str]: (raw_invitation_token, invitation_public_id, email)
        """
        token_hash = hash_token(raw_session_token)
        raw_invitation_token = generate_invitation_token()
        inv_token_hash = hash_token(raw_invitation_token)
        inv_pub_id = generate_public_id(PREFIX_INVITATION)
        audit_pub_id = generate_public_id(PREFIX_AUDIT_EVENT)
        expires_at = datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS)

        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            row = app_session.execute(
                text(
                    """
                    SELECT invitation_id, invitation_public_id
                    FROM public.fn_invitation_create(
                        :token_hash, :email, :role_code, :inv_token_hash,
                        :inv_pub_id, :audit_pub_id, :expires_at
                    )
                    """
                ),
                {
                    "token_hash": token_hash,
                    "email": email,
                    "role_code": role_code,
                    "inv_token_hash": inv_token_hash,
                    "inv_pub_id": inv_pub_id,
                    "audit_pub_id": audit_pub_id,
                    "expires_at": expires_at,
                },
            ).first()
            if not row:
                raise RuntimeError("Failed to create invitation via fn_invitation_create")
            app_session.commit()
            return raw_invitation_token, row.invitation_public_id, email.lower().strip()

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess or sess.active_organisation_id is None:
            raise RuntimeError("Unauthorized: session not found or no active organisation")

        org_id = sess.active_organisation_id
        actor_mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == sess.principal_id,
                OrganisationMembership.status == "active",
            )
        )
        if not actor_mem or actor_mem.role_code not in ("owner", "admin"):
            raise RuntimeError("Forbidden: only owners and admins may invite members")

        if actor_mem.role_code == "admin" and role_code == "owner":
            raise RuntimeError("Forbidden: administrators cannot invite owners")

        norm_email = email.lower().strip()
        # Check active membership
        existing_p = app_session.scalar(select(Principal).where(Principal.email == norm_email))
        if existing_p:
            existing_mem = app_session.scalar(
                select(OrganisationMembership).where(
                    OrganisationMembership.organisation_id == org_id,
                    OrganisationMembership.principal_id == existing_p.id,
                    OrganisationMembership.status == "active",
                )
            )
            if existing_mem:
                raise RuntimeError(
                    f"User with email {email} is already an active member of this organisation"
                )

        inv = OrganisationInvitation(
            public_id=inv_pub_id,
            organisation_id=org_id,
            invited_by_principal_id=sess.principal_id,
            email=norm_email,
            role_code=role_code,
            token_hash=inv_token_hash,
            status="pending",
            expires_at=expires_at,
        )
        app_session.add(inv)
        app_session.add(
            AuditEvent(
                public_id=audit_pub_id,
                organisation_id=org_id,
                actor_principal_id=sess.principal_id,
                event_type="invitation.created",
                subject_type="organisation_invitation",
                subject_public_id=inv_pub_id,
                metadata_json={"role": role_code},
            )
        )
        app_session.commit()
        return raw_invitation_token, inv_pub_id, norm_email

    @staticmethod
    def lookup_invitation(
        app_session: Session, raw_invitation_token: str
    ) -> InvitationDetails | None:
        """Lookup invitation status and details by raw token."""
        inv_token_hash = hash_token(raw_invitation_token)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            row = app_session.execute(
                text(
                    """
                    SELECT invitation_id, invitation_public_id, organisation_name,
                           email, role_code, status, is_expired
                    FROM public.fn_invitation_lookup(:token_hash)
                    """
                ),
                {"token_hash": inv_token_hash},
            ).first()
            if not row:
                return None
            return InvitationDetails(
                invitation_id=row.invitation_id,
                invitation_public_id=row.invitation_public_id,
                organisation_name=row.organisation_name,
                email=row.email,
                role_code=row.role_code,
                status=row.status,
                is_expired=row.is_expired,
            )

        # SQLite fallback
        inv = app_session.scalar(
            select(OrganisationInvitation).where(
                OrganisationInvitation.token_hash == inv_token_hash
            )
        )
        if not inv:
            return None
        org = app_session.scalar(select(Organisation).where(Organisation.id == inv.organisation_id))
        is_expired = datetime.now(UTC) >= _ensure_utc(inv.expires_at)
        return InvitationDetails(
            invitation_id=inv.id,
            invitation_public_id=inv.public_id,
            organisation_name=org.name if org else "",
            email=inv.email,
            role_code=inv.role_code,
            status=inv.status,
            is_expired=is_expired,
        )

    @staticmethod
    def accept_invitation(
        app_session: Session,
        raw_session_token: str,
        raw_invitation_token: str,
    ) -> tuple[int, int, str]:
        """Accept an invitation bound to authenticated session.

        Cross-email guard: caller email must match invitation email.
        Returns:
            tuple[int, int, str]: (membership_id, organisation_id, role_code)
        """
        token_hash = hash_token(raw_session_token)
        inv_token_hash = hash_token(raw_invitation_token)
        mem_pub_id = generate_public_id(PREFIX_MEMBERSHIP)
        audit_1 = generate_public_id(PREFIX_AUDIT_EVENT)
        audit_2 = generate_public_id(PREFIX_AUDIT_EVENT)

        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            row = _exec_control_plane_fn(
                app_session,
                """
                    SELECT membership_id, organisation_id, role_code
                    FROM public.fn_invitation_accept_with_mutex(
                        :token_hash, :inv_token_hash, :mem_pub_id, :audit_1, :audit_2
                    )
                    """,
                {
                    "token_hash": token_hash,
                    "inv_token_hash": inv_token_hash,
                    "mem_pub_id": mem_pub_id,
                    "audit_1": audit_1,
                    "audit_2": audit_2,
                },
            )
            if not row:
                raise RuntimeError(
                    "Failed to accept invitation via fn_invitation_accept_with_mutex"
                )
            app_session.commit()
            return row.membership_id, row.organisation_id, row.role_code

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess:
            raise RuntimeError("Unauthorized: invalid or expired session")

        p = app_session.scalar(select(Principal).where(Principal.id == sess.principal_id))
        inv = app_session.scalar(
            select(OrganisationInvitation).where(
                OrganisationInvitation.token_hash == inv_token_hash
            )
        )
        if not inv or inv.status != "pending" or now >= _ensure_utc(inv.expires_at):
            raise RuntimeError("Invitation not found, expired, or already accepted")

        if p.email.lower().strip() != inv.email.lower().strip():
            raise RuntimeError("Invitation email does not match authenticated user")

        inv.status = "accepted"
        inv.accepted_at = now

        mem = OrganisationMembership(
            public_id=mem_pub_id,
            organisation_id=inv.organisation_id,
            principal_id=p.id,
            role_code=inv.role_code,
            status="active",
            auth_version=1,
        )
        app_session.add(mem)
        app_session.flush()

        app_session.add(
            AuditEvent(
                public_id=audit_1,
                organisation_id=inv.organisation_id,
                actor_principal_id=p.id,
                event_type="invitation.accepted",
                subject_type="organisation_invitation",
                subject_public_id=inv.public_id,
                metadata_json={"accepted_by_principal_id": p.id},
            )
        )
        app_session.add(
            AuditEvent(
                public_id=audit_2,
                organisation_id=inv.organisation_id,
                actor_principal_id=p.id,
                event_type="membership.assigned",
                subject_type="organisation_membership",
                subject_public_id=mem_pub_id,
                metadata_json={"role": inv.role_code},
            )
        )
        app_session.commit()
        return mem.id, inv.organisation_id, inv.role_code

    @staticmethod
    def revoke_invitation(
        app_session: Session, raw_session_token: str, invitation_public_id: str
    ) -> bool:
        """Revoke a pending invitation."""
        token_hash = hash_token(raw_session_token)
        audit_pub_id = generate_public_id(PREFIX_AUDIT_EVENT)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            res = app_session.execute(
                text(
                    """
                    SELECT public.fn_invitation_revoke(
                        :token_hash, :inv_pub_id, :audit_pub_id
                    )
                    """
                ),
                {
                    "token_hash": token_hash,
                    "inv_pub_id": invitation_public_id,
                    "audit_pub_id": audit_pub_id,
                },
            ).scalar()
            app_session.commit()
            return bool(res)

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess or sess.active_organisation_id is None:
            raise RuntimeError("Unauthorized: session not found or no active organisation")

        org_id = sess.active_organisation_id
        actor_mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == sess.principal_id,
                OrganisationMembership.status == "active",
            )
        )
        if not actor_mem or actor_mem.role_code not in ("owner", "admin"):
            raise RuntimeError("Forbidden: only owners and admins may revoke invitations")

        inv = app_session.scalar(
            select(OrganisationInvitation).where(
                OrganisationInvitation.public_id == invitation_public_id,
                OrganisationInvitation.organisation_id == org_id,
                OrganisationInvitation.status == "pending",
            )
        )
        if not inv:
            return False

        inv.status = "revoked"
        inv.revoked_at = now
        app_session.add(
            AuditEvent(
                public_id=audit_pub_id,
                organisation_id=org_id,
                actor_principal_id=sess.principal_id,
                event_type="invitation.revoked",
                subject_type="organisation_invitation",
                subject_public_id=inv.public_id,
                metadata_json={},
            )
        )
        app_session.commit()
        return True

    @staticmethod
    def list_invitations(app_session: Session, raw_session_token: str) -> list[InvitationListItem]:
        """List all invitations in caller's active organisation."""
        token_hash = hash_token(raw_session_token)
        bind = app_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            rows = app_session.execute(
                text(
                    """
                    SELECT invitation_public_id, email, role_code, status, expires_at, created_at
                    FROM public.fn_invitation_list(:token_hash)
                    """
                ),
                {"token_hash": token_hash},
            ).all()
            return [
                InvitationListItem(
                    invitation_public_id=r.invitation_public_id,
                    email=r.email,
                    role_code=r.role_code,
                    status=r.status,
                    expires_at=r.expires_at,
                    created_at=r.created_at,
                )
                for r in rows
            ]

        # SQLite fallback
        now = datetime.now(UTC)
        sess = app_session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.idle_expires_at > now,
            )
        )
        if not sess or sess.active_organisation_id is None:
            raise RuntimeError("Unauthorized: session not found or no active organisation")

        org_id = sess.active_organisation_id
        actor_mem = app_session.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == org_id,
                OrganisationMembership.principal_id == sess.principal_id,
                OrganisationMembership.status == "active",
            )
        )
        if not actor_mem or actor_mem.role_code not in ("owner", "admin"):
            raise RuntimeError("Forbidden: only owners and admins may view invitations")

        invs = app_session.scalars(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.organisation_id == org_id)
            .order_by(OrganisationInvitation.created_at.desc())
        ).all()
        return [
            InvitationListItem(
                invitation_public_id=i.public_id,
                email=i.email,
                role_code=i.role_code,
                status=i.status,
                expires_at=i.expires_at,
                created_at=i.created_at,
            )
            for i in invs
        ]

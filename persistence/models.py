"""SQLAlchemy declarative models for Untangle multi-tenant persistence.

Includes composite foreign keys, strict CHECK constraints, lifecycle state machines,
and non-enumerable public identifiers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import JSON

# Cross-dialect JSON type that uses JSONB on PostgreSQL and JSON on SQLite
JSONType = JSON().with_variant(JSONB, "postgresql")

# Cross-dialect integer primary key type: BigInteger on PostgreSQL, Integer on SQLite
IDType = BigInteger().with_variant(Integer, "sqlite")


class HexHashCheck(ColumnElement[bool]):
    """Dialect-portable hex hash validation check constraint."""

    def __init__(self, column_name: str, length: int = 64, nullable: bool = False) -> None:
        super().__init__()
        self.column_name = column_name
        self.length = length
        self.nullable = nullable


@compiles(HexHashCheck, "postgresql")
def _compile_hex_hash_pg(element: HexHashCheck, compiler: Any, **kw: Any) -> str:
    pattern = f"^[0-9a-f]{{{element.length}}}$"
    if element.nullable:
        return f"({element.column_name} IS NULL OR {element.column_name} ~ '{pattern}')"
    return f"({element.column_name} ~ '{pattern}')"


@compiles(HexHashCheck, "sqlite")
def _compile_hex_hash_sqlite(element: HexHashCheck, compiler: Any, **kw: Any) -> str:
    if element.nullable:
        return (
            f"({element.column_name} IS NULL OR "
            f"(length({element.column_name}) = {element.length} AND NOT ({element.column_name} GLOB '*[^0-9a-f]*')))"
        )
    return f"(length({element.column_name}) = {element.length} AND NOT ({element.column_name} GLOB '*[^0-9a-f]*'))"


@compiles(HexHashCheck)
def _compile_hex_hash_default(element: HexHashCheck, compiler: Any, **kw: Any) -> str:
    if element.nullable:
        return (
            f"({element.column_name} IS NULL OR length({element.column_name}) = {element.length})"
        )
    return f"(length({element.column_name}) = {element.length})"


class Base(DeclarativeBase):
    """Base class for all persistence models."""


# ---------------------------------------------------------------------------
# Control-Plane Models (No tenant-level RLS)
# ---------------------------------------------------------------------------


class Organisation(Base):
    """An Untangle organisation tenant."""

    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(is_active = true AND deleted_at IS NULL) OR (is_active = false AND deleted_at IS NOT NULL)",
            name="chk_org_active_deleted",
        ),
    )


class Principal(Base):
    """A user or service principal identity."""

    __tablename__ = "principals"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(is_active = true AND deleted_at IS NULL) OR (is_active = false AND deleted_at IS NOT NULL)",
            name="chk_principal_active_deleted",
        ),
    )


class RoleModel(Base):
    """Authoritative role taxonomy."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "code IN ('owner', 'admin', 'operator', 'reviewer', 'auditor')",
            name="chk_roles_code_allowed",
        ),
    )


class OrganisationMembership(Base):
    """Membership binding a principal to an organisation with a verified role."""

    __tablename__ = "organisation_memberships"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role_code: Mapped[str] = mapped_column(String(32), ForeignKey("roles.code"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("organisation_id", "principal_id", name="uq_memberships_org_principal"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'invited')",
            name="chk_memberships_status_allowed",
        ),
        CheckConstraint("auth_version > 0", name="chk_memberships_auth_version_positive"),
    )


class TrustedAuthIssuer(Base):
    """Trusted OpenID Connect identity provider configuration (migrator-controlled)."""

    __tablename__ = "trusted_auth_issuers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issuer_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FederatedIdentity(Base):
    """Federated external identity (issuer, subject) mapped to an internal principal."""

    __tablename__ = "federated_identities"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_at_auth: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_federated_issuer_subject"),
        CheckConstraint("email_verified = true", name="chk_federated_email_verified"),
    )


class OidcAuthTransaction(Base):
    """Short-lived single-use OIDC authentication transaction."""

    __tablename__ = "oidc_auth_transactions"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    return_to: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            HexHashCheck("state_hash", 64, nullable=False), name="chk_oidc_tx_state_hex"
        ),
        CheckConstraint(
            HexHashCheck("nonce_hash", 64, nullable=False), name="chk_oidc_tx_nonce_hex"
        ),
        CheckConstraint("expires_at > created_at", name="chk_oidc_tx_expiry_order"),
    )


class UserSession(Base):
    """Authenticated user session state."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    active_organisation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    membership_auth_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent_truncated: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            HexHashCheck("session_token_hash", 64, nullable=False),
            name="chk_sessions_token_hash_hex",
        ),
        CheckConstraint(
            HexHashCheck("ip_hash", 64, nullable=False), name="chk_sessions_ip_hash_hex"
        ),
        CheckConstraint(
            "membership_auth_version IS NULL OR membership_auth_version > 0",
            name="chk_sessions_membership_version_positive",
        ),
        CheckConstraint(
            "last_active_at <= idle_expires_at AND idle_expires_at <= absolute_expires_at",
            name="chk_sessions_timestamp_ordering",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="chk_sessions_revoked_after_created",
        ),
        CheckConstraint(
            "(active_organisation_id IS NULL AND membership_auth_version IS NULL) OR "
            "(active_organisation_id IS NOT NULL AND membership_auth_version IS NOT NULL)",
            name="chk_sessions_org_version_consistency",
        ),
    )


class OrganisationInvitation(Base):
    """Single-use organisation membership invitation."""

    __tablename__ = "organisation_invitations"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invited_by_principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role_code: Mapped[str] = mapped_column(String(32), ForeignKey("roles.code"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            HexHashCheck("token_hash", 64, nullable=False), name="chk_invitations_token_hash_hex"
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="chk_invitations_status",
        ),
        CheckConstraint(
            "("
            "(status = 'pending' AND accepted_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'accepted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND accepted_at IS NULL) OR "
            "(status = 'expired' AND accepted_at IS NULL)"
            ")",
            name="chk_invitations_lifecycle",
        ),
        CheckConstraint("expires_at > created_at", name="chk_invitations_expiry_order"),
    )


class ControlPlaneSecurityEvent(Base):
    """Immutable control-plane security event (pre-auth and system-level events)."""

    __tablename__ = "control_plane_security_events"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_principal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent_truncated: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'auth.oidc.initiated', 'auth.oidc.callback_success', 'auth.oidc.callback_failed', "
            "'auth.session.created', 'auth.session.expired', 'auth.session.revoked', "
            "'auth.session.stale_invalidated', 'auth.csrf.violation', 'auth.rate_limit.exceeded', "
            "'auth.identity.collision'"
            ")",
            name="chk_sec_events_type",
        ),
        CheckConstraint("length(subject_identifier) <= 255", name="chk_sec_events_subject_len"),
    )


# ---------------------------------------------------------------------------
# Tenant Data-Plane Models (Protected by PostgreSQL RLS)
# ---------------------------------------------------------------------------


class ReconciliationRun(Base):
    """One deterministic reconciliation run owned by an organisation."""

    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="initiated", nullable=False)
    reconciliation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_statement_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recon_report_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_ledger_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_pack_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_pack_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reporting_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    reporting_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_pack_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_adapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_reconciliation_runs_org_id"),
        CheckConstraint(
            "status IN ('initiated', 'running', 'completed', 'failed', 'aborted')",
            name="chk_runs_status_allowed",
        ),
        CheckConstraint(
            "("
            "(status = 'initiated' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at >= started_at AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL AND error_code IS NOT NULL) OR "
            "(status = 'aborted' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL)"
            ")",
            name="chk_runs_lifecycle_state_machine",
        ),
        CheckConstraint(
            "(is_deleted = false AND deleted_at IS NULL) OR (is_deleted = true AND deleted_at IS NOT NULL)",
            name="chk_runs_soft_delete_consistency",
        ),
        CheckConstraint(
            HexHashCheck("reconciliation_hash", 64, nullable=True),
            name="chk_runs_recon_hash_hex",
        ),
        CheckConstraint(
            "(reporting_period_start IS NULL AND reporting_period_end IS NULL) OR "
            "(reporting_period_start IS NOT NULL AND reporting_period_end IS NOT NULL AND reporting_period_start <= reporting_period_end)",
            name="chk_runs_period_order",
        ),
    )


class UploadedFileMetadata(Base):
    """Metadata and content hash for uploaded input files bound to a run."""

    __tablename__ = "uploaded_file_metadata"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    file_role: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    backend: Mapped[str] = mapped_column(
        String(32), server_default="s3", default="s3", nullable=False
    )
    object_key: Mapped[str] = mapped_column(
        String(512), server_default="", default="", nullable=False
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(32), server_default="active", default="active", nullable=False
    )
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encryption_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_uploaded_files_org_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_uploaded_files_org",
        ),
        UniqueConstraint(
            "organisation_id", "run_id", "file_role", name="uq_uploaded_files_run_role"
        ),
        CheckConstraint(
            "file_role IN ('bank_statement', 'recon_report', 'order_ledger')",
            name="chk_uploaded_files_role_allowed",
        ),
        CheckConstraint("size_bytes >= 0", name="chk_uploaded_files_size_nonnegative"),
        CheckConstraint(
            HexHashCheck("sha256_checksum", 64, nullable=False),
            name="chk_uploaded_files_sha256_hex",
        ),
        CheckConstraint(
            "lifecycle_state IN ('staged', 'active', 'tombstoned', 'purged')",
            name="chk_uploaded_files_lifecycle_allowed",
        ),
        CheckConstraint(
            "backend IN ('s3', 'local')",
            name="chk_uploaded_files_backend_allowed",
        ),
        CheckConstraint(
            "(tombstone = false AND lifecycle_state != 'tombstoned') OR (tombstone = true AND lifecycle_state IN ('tombstoned', 'purged'))",
            name="chk_uploaded_files_tombstone_consistency",
        ),
    )


class ReconciliationResult(Base):
    """Canonical reconciliation result metadata and exact report text bound to a run."""

    __tablename__ = "reconciliation_results"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    presentation_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    canonical_report_text: Mapped[str] = mapped_column(Text, nullable=False)
    audit_root: Mapped[str] = mapped_column(String(64), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_results_org_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_results_org",
        ),
        UniqueConstraint("organisation_id", "run_id", name="uq_results_org_run"),
        CheckConstraint(
            HexHashCheck("audit_root", 64, nullable=False),
            name="chk_results_audit_root_hex",
        ),
        CheckConstraint(
            HexHashCheck("report_sha256", 64, nullable=False),
            name="chk_results_report_sha256_hex",
        ),
    )


class InvestigationRecord(Base):
    """Deterministic root-cause investigation case for a credit line variance."""

    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    line_key: Mapped[str] = mapped_column(String(64), nullable=False)
    root_cause: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    variance_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_investigations_org_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_investigations_org",
        ),
        UniqueConstraint(
            "organisation_id", "run_id", "line_key", name="uq_investigations_org_run_line"
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="chk_investigations_confidence_bounds",
        ),
        CheckConstraint(
            "root_cause IN ("
            "'mdr_fee_drift', 'cross_cycle_refund_lag', 'on_hold_release', "
            "'dispute_deduction', 'partial_capture', 'bank_charge_or_rounding', "
            "'rolling_reserve', 'unexplained'"
            ")",
            name="chk_investigations_root_cause_allowed",
        ),
    )


class CertificateRecord(Base):
    """Immutable close certificate issued for a reconciliation period."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_signed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_certificates_org_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_certificates_org",
        ),
        UniqueConstraint("organisation_id", "run_id", name="uq_certificates_org_run"),
        CheckConstraint(
            HexHashCheck("content_sha256", 64, nullable=False),
            name="chk_certificates_content_sha256_hex",
        ),
        CheckConstraint(
            HexHashCheck("report_sha256", 64, nullable=False),
            name="chk_certificates_report_sha256_hex",
        ),
        CheckConstraint(
            "("
            "(is_signed = false AND signature IS NULL AND public_key_pem IS NULL) OR "
            "(is_signed = true AND signature IS NOT NULL AND public_key_pem IS NOT NULL)"
            ")",
            name="chk_certificates_signature_consistency",
        ),
    )


class ArtifactMetadata(Base):
    """Metadata and content hash for downloadable artifacts (Tally XML, JSON reports)."""

    __tablename__ = "artifact_metadata"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    backend: Mapped[str] = mapped_column(
        String(32), server_default="s3", default="s3", nullable=False
    )
    object_key: Mapped[str] = mapped_column(
        String(512), server_default="", default="", nullable=False
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(32), server_default="active", default="active", nullable=False
    )
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encryption_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_artifacts_org_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_artifacts_org",
        ),
        UniqueConstraint(
            "organisation_id", "run_id", "artifact_type", name="uq_artifacts_org_run_type"
        ),
        CheckConstraint(
            "artifact_type IN ('tally_xml', 'report_json', 'certificate_json', 'recovery_json')",
            name="chk_artifacts_type_allowed",
        ),
        CheckConstraint("size_bytes >= 0", name="chk_artifacts_size_nonnegative"),
        CheckConstraint(
            HexHashCheck("content_sha256", 64, nullable=False),
            name="chk_artifacts_content_sha256_hex",
        ),
        CheckConstraint(
            "lifecycle_state IN ('staged', 'active', 'tombstoned', 'purged')",
            name="chk_artifacts_lifecycle_allowed",
        ),
        CheckConstraint(
            "backend IN ('s3', 'local')",
            name="chk_artifacts_backend_allowed",
        ),
        CheckConstraint(
            "(tombstone = false AND lifecycle_state != 'tombstoned') OR (tombstone = true AND lifecycle_state IN ('tombstoned', 'purged'))",
            name="chk_artifacts_tombstone_consistency",
        ),
    )


class AuditEvent(Base):
    """Immutable, append-only application audit event."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_principal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'run.initiated', 'run.completed', 'run.failed', 'certificate.issued', "
            "'membership.assigned', 'organisation.deactivated', "
            "'organisation.created', 'organisation.switched', 'invitation.created', "
            "'invitation.accepted', 'invitation.revoked', 'membership.role_changed', "
            "'membership.suspended', 'membership.reactivated', 'run.deleted', "
            "'run.purged', 'run.legal_hold_placed', 'run.legal_hold_released'"
            ")",
            name="chk_audit_events_type_allowed",
        ),
        CheckConstraint(
            "subject_type IN ('reconciliation_run', 'certificate', 'organisation_membership', 'organisation', 'organisation_invitation')",
            name="chk_audit_events_subject_allowed",
        ),
    )


class ReconciliationJob(Base):
    """Durable asynchronous job record for a tenant reconciliation run."""

    __tablename__ = "reconciliation_jobs"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_principal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_jobs_org_run",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_jobs_status_allowed",
        ),
        CheckConstraint(
            "stage IN ('queued', 'ingesting', 'attributing', 'reconciling', 'investigating', 'persisting', 'completed')",
            name="chk_jobs_stage_allowed",
        ),
        CheckConstraint(
            "("
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND failed_at IS NULL AND attempt_token IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND attempt_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at >= started_at AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL AND error_code IS NOT NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND completed_at IS NULL)"
            ")",
            name="chk_jobs_lifecycle_state_machine",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="chk_jobs_attempt_bounds",
        ),
        CheckConstraint("lease_generation >= 0", name="chk_jobs_generation_bounds"),
    )


class IdempotencyRecord(Base):
    """Persistent idempotency token for reconciliation requests."""

    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(IDType, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reconciliation_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    response_status_code: Mapped[int] = mapped_column(Integer, default=202, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("organisation_id", "idempotency_key", name="uq_idempotency_org_key"),
        CheckConstraint(
            HexHashCheck("request_hash", 64, nullable=False),
            name="chk_idempotency_hash_hex",
        ),
    )

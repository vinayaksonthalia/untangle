"""Authentication, federated identity, sessions, invitations, and server-enforced permissions.

Revision ID: 0002_auth_federation_sessions
Revises: 0001_initial_tenant_schema
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0002_auth_federation_sessions"
down_revision: str | None = "0001_initial_tenant_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATION_PROVENANCE: dict[str, str] = {
    "created_by": "vinayaksonthalia",
    "created_at": "2026-09-05T09:47:29Z",
    "source": "docs/AUTHENTICATION_AND_PERMISSIONS.md#entity--ownership-model",
}

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def pk_id_column() -> sa.Column:
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer, "sqlite"),
        sa.Identity(always=False),
        primary_key=True,
        autoincrement=True,
    )


def hex_hash_check_sql(
    is_postgres: bool, col: str, length: int = 64, nullable: bool = False
) -> str:
    if is_postgres:
        pattern = f"^[0-9a-f]{{{length}}}$"
        if nullable:
            return f"{col} IS NULL OR {col} ~ '{pattern}'"
        return f"{col} ~ '{pattern}'"
    if nullable:
        return f"{col} IS NULL OR (length({col}) = {length} AND NOT ({col} GLOB '*[^0-9a-f]*'))"
    return f"length({col}) = {length} AND NOT ({col} GLOB '*[^0-9a-f]*')"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. trusted_auth_issuers (migrator-controlled)
    op.create_table(
        "trusted_auth_issuers",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.Integer, "sqlite"),
            sa.Identity(always=False),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("issuer_url", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("issuer_url", name="trusted_auth_issuers_issuer_url_key"),
    )
    op.create_index("ix_trusted_issuers_url", "trusted_auth_issuers", ["issuer_url"])

    # 2. federated_identities
    op.create_table(
        "federated_identities",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_auth", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="federated_identities_public_id_key"),
        sa.UniqueConstraint("issuer", "subject", name="uq_federated_issuer_subject"),
        sa.CheckConstraint(
            "email_verified = true" if is_postgres else "email_verified = 1",
            name="chk_federated_email_verified",
        ),
    )
    op.create_index("ix_federated_principal_id", "federated_identities", ["principal_id"])
    op.create_index("ix_federated_public_id", "federated_identities", ["public_id"])

    # 3. oidc_auth_transactions
    op.create_table(
        "oidc_auth_transactions",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("nonce_hash", sa.String(64), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("return_to", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="oidc_auth_transactions_public_id_key"),
        sa.UniqueConstraint("state_hash", name="oidc_auth_transactions_state_hash_key"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "state_hash", 64, nullable=False),
            name="chk_oidc_tx_state_hex",
        ),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "nonce_hash", 64, nullable=False),
            name="chk_oidc_tx_nonce_hex",
        ),
        sa.CheckConstraint("expires_at > created_at", name="chk_oidc_tx_expiry_order"),
    )
    op.create_index("ix_oidc_tx_public_id", "oidc_auth_transactions", ["public_id"])
    op.create_index("ix_oidc_tx_state_hash", "oidc_auth_transactions", ["state_hash"])
    op.create_index("ix_oidc_tx_expires_at", "oidc_auth_transactions", ["expires_at"])

    # 4. user_sessions
    op.create_table(
        "user_sessions",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_token_hash", sa.String(64), nullable=False),
        sa.Column(
            "active_organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("membership_auth_version", sa.Integer(), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_truncated", sa.String(128), nullable=True),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="user_sessions_public_id_key"),
        sa.UniqueConstraint("session_token_hash", name="user_sessions_session_token_hash_key"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "session_token_hash", 64, nullable=False),
            name="chk_sessions_token_hash_hex",
        ),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "ip_hash", 64, nullable=False),
            name="chk_sessions_ip_hash_hex",
        ),
        sa.CheckConstraint(
            "membership_auth_version IS NULL OR membership_auth_version > 0",
            name="chk_sessions_membership_version_positive",
        ),
        sa.CheckConstraint(
            "last_active_at <= idle_expires_at AND idle_expires_at <= absolute_expires_at",
            name="chk_sessions_timestamp_ordering",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="chk_sessions_revoked_after_created",
        ),
        sa.CheckConstraint(
            "(active_organisation_id IS NULL AND membership_auth_version IS NULL) OR "
            "(active_organisation_id IS NOT NULL AND membership_auth_version IS NOT NULL)",
            name="chk_sessions_org_version_consistency",
        ),
    )
    op.create_index("ix_user_sessions_public_id", "user_sessions", ["public_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["session_token_hash"])
    op.create_index("ix_user_sessions_principal_id", "user_sessions", ["principal_id"])
    op.create_index("ix_user_sessions_active_org_id", "user_sessions", ["active_organisation_id"])
    op.create_index("ix_user_sessions_idle_expires_at", "user_sessions", ["idle_expires_at"])

    # 5. organisation_invitations
    op.create_table(
        "organisation_invitations",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role_code", sa.String(32), sa.ForeignKey("roles.code"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="organisation_invitations_public_id_key"),
        sa.UniqueConstraint("token_hash", name="organisation_invitations_token_hash_key"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "token_hash", 64, nullable=False),
            name="chk_invitations_token_hash_hex",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="chk_invitations_status",
        ),
        sa.CheckConstraint(
            "("
            "(status = 'pending' AND accepted_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'accepted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND accepted_at IS NULL) OR "
            "(status = 'expired' AND accepted_at IS NULL)"
            ")",
            name="chk_invitations_lifecycle",
        ),
        sa.CheckConstraint("expires_at > created_at", name="chk_invitations_expiry_order"),
    )
    op.create_index("ix_org_invitations_public_id", "organisation_invitations", ["public_id"])
    op.create_index("ix_org_invitations_org_id", "organisation_invitations", ["organisation_id"])
    op.create_index("ix_org_invitations_token_hash", "organisation_invitations", ["token_hash"])
    op.create_index(
        "uq_org_invitations_pending_email",
        "organisation_invitations",
        ["organisation_id", sa.text("lower(trim(email))")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    # 6. control_plane_security_events
    op.create_table(
        "control_plane_security_events",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "actor_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_identifier", sa.String(255), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_truncated", sa.String(128), nullable=True),
        sa.Column("details_json", JSONType, server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="control_plane_security_events_public_id_key"),
        sa.CheckConstraint(
            "event_type IN ("
            "'auth.oidc.initiated', 'auth.oidc.callback_success', 'auth.oidc.callback_failed', "
            "'auth.session.created', 'auth.session.expired', 'auth.session.revoked', "
            "'auth.session.stale_invalidated', 'auth.csrf.violation', 'auth.rate_limit.exceeded', "
            "'auth.identity.collision'"
            ")",
            name="chk_sec_events_type",
        ),
        sa.CheckConstraint("length(subject_identifier) <= 255", name="chk_sec_events_subject_len"),
        sa.CheckConstraint(
            "pg_column_size(details_json) <= 4096"
            if is_postgres
            else "length(cast(details_json as text)) <= 4096",
            name="chk_sec_events_json_size",
        ),
    )
    op.create_index(
        "ix_sec_events_public_id", "control_plane_security_events", ["public_id"]
    )
    op.create_index(
        "ix_sec_events_created_at", "control_plane_security_events", ["created_at"]
    )
    op.create_index(
        "ix_sec_events_event_type", "control_plane_security_events", ["event_type"]
    )

    # 7. Modify existing tables
    # organisation_memberships: auth_version
    with op.batch_alter_table("organisation_memberships") as batch_op:
        batch_op.add_column(
            sa.Column("auth_version", sa.Integer(), server_default="1", nullable=False)
        )
        if is_postgres:
            batch_op.create_check_constraint(
                "chk_memberships_auth_version_positive",
                "auth_version > 0",
            )

    # audit_events: update check constraints
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("chk_audit_events_type_allowed", type_="check")
        batch_op.drop_constraint("chk_audit_events_subject_allowed", type_="check")
        batch_op.create_check_constraint(
            "chk_audit_events_type_allowed",
            "event_type IN ("
            "'run.initiated', 'run.completed', 'run.failed', 'certificate.issued', "
            "'membership.assigned', 'organisation.deactivated', "
            "'organisation.created', 'organisation.switched', 'invitation.created', "
            "'invitation.accepted', 'invitation.revoked', 'membership.role_changed', "
            "'membership.suspended', 'membership.reactivated'"
            ")",
        )
        batch_op.create_check_constraint(
            "chk_audit_events_subject_allowed",
            "subject_type IN ('reconciliation_run', 'certificate', 'organisation_membership', 'organisation', 'organisation_invitation')",
        )

    # -----------------------------------------------------------------------
    # PostgreSQL-Specific: Roles, Privileges, 23 Functions, and Audit Policy
    # -----------------------------------------------------------------------
    if is_postgres:
        # Schema permissions
        op.execute("GRANT untangle_fn_owner TO untangle_migrator;")
        op.execute("ALTER SCHEMA public OWNER TO untangle_migrator;")
        op.execute("GRANT USAGE ON SCHEMA public TO untangle_app, untangle_auth, untangle_maintenance;")
        op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")
        op.execute("REVOKE CREATE ON SCHEMA public FROM untangle_app, untangle_auth, untangle_maintenance;")

        # Table & sequence grants to untangle_fn_owner
        op.execute(
            """
            GRANT SELECT ON public.trusted_auth_issuers TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE ON public.organisations TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE ON public.principals TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE ON public.federated_identities TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE, DELETE ON public.organisation_memberships TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_sessions TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE ON public.organisation_invitations TO untangle_fn_owner;
            GRANT SELECT, INSERT, UPDATE, DELETE ON public.oidc_auth_transactions TO untangle_fn_owner;
            GRANT SELECT, INSERT, DELETE ON public.control_plane_security_events TO untangle_fn_owner;
            GRANT SELECT, INSERT ON public.audit_events TO untangle_fn_owner;

            GRANT USAGE, SELECT ON SEQUENCE organisations_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE principals_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE federated_identities_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE organisation_memberships_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE user_sessions_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE organisation_invitations_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE oidc_auth_transactions_id_seq TO untangle_fn_owner;
            GRANT USAGE, SELECT ON SEQUENCE control_plane_security_events_id_seq TO untangle_fn_owner;
            """
        )

        # Audit insertion policy for untangle_fn_owner under forced RLS
        op.execute(
            """
            CREATE POLICY fn_owner_audit_insert_policy ON public.audit_events
                FOR INSERT
                TO untangle_fn_owner
                WITH CHECK (organisation_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint);
            """
        )

        # -------------------------------------------------------------------
        # 23 SECURITY DEFINER Functions
        # -------------------------------------------------------------------

        # 1. fn_oidc_create_transaction
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_oidc_create_transaction(
                p_public_id VARCHAR(64),
                p_state_hash VARCHAR(64),
                p_nonce_hash VARCHAR(64),
                p_code_verifier_encrypted TEXT,
                p_return_to VARCHAR(255),
                p_expires_at TIMESTAMPTZ
            )
            RETURNS VOID
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                INSERT INTO public.oidc_auth_transactions (
                    public_id, state_hash, nonce_hash, code_verifier_encrypted, return_to, expires_at, created_at
                ) VALUES (
                    p_public_id, p_state_hash, p_nonce_hash, p_code_verifier_encrypted, p_return_to, p_expires_at, NOW()
                );
            END;
            $$;
            ALTER FUNCTION public.fn_oidc_create_transaction(VARCHAR, VARCHAR, VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_oidc_create_transaction(VARCHAR, VARCHAR, VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_oidc_create_transaction(VARCHAR, VARCHAR, VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ) TO untangle_auth;
            """
        )

        # 2. fn_oidc_consume_transaction
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_oidc_consume_transaction(
                p_state_hash VARCHAR(64)
            )
            RETURNS TABLE (nonce_hash VARCHAR(64), code_verifier_encrypted TEXT, return_to VARCHAR(255))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                RETURN QUERY
                UPDATE public.oidc_auth_transactions
                SET consumed_at = NOW()
                WHERE oidc_auth_transactions.state_hash = p_state_hash
                  AND oidc_auth_transactions.consumed_at IS NULL
                  AND oidc_auth_transactions.expires_at > NOW()
                RETURNING oidc_auth_transactions.nonce_hash, oidc_auth_transactions.code_verifier_encrypted, oidc_auth_transactions.return_to;
            END;
            $$;
            ALTER FUNCTION public.fn_oidc_consume_transaction(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_oidc_consume_transaction(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_oidc_consume_transaction(VARCHAR) TO untangle_auth;
            """
        )

        # 3. fn_auth_resolve_federated_identity
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_resolve_federated_identity(
                p_issuer VARCHAR(255),
                p_subject VARCHAR(255),
                p_email VARCHAR(255),
                p_display_name VARCHAR(255),
                p_principal_public_id VARCHAR(64),
                p_fed_public_id VARCHAR(64)
            )
            RETURNS TABLE (principal_id BIGINT, principal_public_id VARCHAR(64), is_new BOOLEAN)
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_principal_id BIGINT;
                v_principal_public_id VARCHAR(64);
                v_is_active BOOLEAN;
                v_norm_email VARCHAR(255);
            BEGIN
                v_norm_email := lower(trim(p_email));

                IF NOT EXISTS (
                    SELECT 1 FROM public.trusted_auth_issuers 
                    WHERE issuer_url = p_issuer AND is_active = TRUE
                ) THEN
                    RAISE EXCEPTION 'Untrusted or inactive identity provider: %', p_issuer USING ERRCODE = '42501';
                END IF;

                SELECT fi.principal_id, p.public_id, p.is_active
                INTO v_principal_id, v_principal_public_id, v_is_active
                FROM public.federated_identities fi
                JOIN public.principals p ON p.id = fi.principal_id
                WHERE fi.issuer = p_issuer AND fi.subject = p_subject;

                IF FOUND THEN
                    IF v_is_active = FALSE THEN
                        RAISE EXCEPTION 'Principal account is deactivated' USING ERRCODE = '42501';
                    END IF;

                    UPDATE public.federated_identities
                    SET email_at_auth = v_norm_email, updated_at = NOW()
                    WHERE issuer = p_issuer AND subject = p_subject;

                    UPDATE public.principals
                    SET display_name = p_display_name, updated_at = NOW()
                    WHERE id = v_principal_id;

                    RETURN QUERY SELECT v_principal_id, v_principal_public_id, FALSE;
                    RETURN;
                END IF;

                IF EXISTS (
                    SELECT 1 FROM public.principals WHERE lower(email) = v_norm_email
                ) THEN
                    RAISE EXCEPTION 'Principal with email % already exists (identity collision)', p_email USING ERRCODE = 'P0004';
                END IF;

                INSERT INTO public.principals (public_id, email, display_name, is_active, created_at, updated_at)
                VALUES (p_principal_public_id, v_norm_email, p_display_name, TRUE, NOW(), NOW())
                RETURNING id, public.principals.public_id INTO v_principal_id, v_principal_public_id;

                INSERT INTO public.federated_identities (public_id, principal_id, issuer, subject, email_at_auth, email_verified, created_at, updated_at)
                VALUES (p_fed_public_id, v_principal_id, p_issuer, p_subject, v_norm_email, TRUE, NOW(), NOW());

                RETURN QUERY SELECT v_principal_id, v_principal_public_id, TRUE;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_resolve_federated_identity(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_resolve_federated_identity(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_resolve_federated_identity(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) TO untangle_auth;
            """
        )

        # 4. fn_auth_create_session
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_create_session(
                p_public_id VARCHAR(64),
                p_principal_id BIGINT,
                p_session_token_hash VARCHAR(64),
                p_active_org_id BIGINT,
                p_ip_hash VARCHAR(64),
                p_user_agent_truncated VARCHAR(128),
                p_idle_exp TIMESTAMPTZ,
                p_abs_exp TIMESTAMPTZ
            )
            RETURNS TABLE (session_id BIGINT, session_public_id VARCHAR(64))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_auth_ver INT := NULL;
                v_sess_id BIGINT;
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM public.principals WHERE id = p_principal_id AND is_active = TRUE) THEN
                    RAISE EXCEPTION 'Principal not found or inactive' USING ERRCODE = '42501';
                END IF;

                IF p_active_org_id IS NOT NULL THEN
                    SELECT m.auth_version INTO v_auth_ver
                    FROM public.organisation_memberships m
                    JOIN public.organisations o ON o.id = m.organisation_id
                    WHERE m.organisation_id = p_active_org_id AND m.principal_id = p_principal_id
                      AND m.status = 'active' AND o.is_active = TRUE;

                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'No active membership in organisation %', p_active_org_id USING ERRCODE = '42501';
                    END IF;
                END IF;

                INSERT INTO public.user_sessions (
                    public_id, principal_id, session_token_hash, active_organisation_id,
                    membership_auth_version, ip_hash, user_agent_truncated,
                    last_active_at, idle_expires_at, absolute_expires_at, revoked_at, created_at
                ) VALUES (
                    p_public_id, p_principal_id, p_session_token_hash, p_active_org_id,
                    v_auth_ver, p_ip_hash, p_user_agent_truncated,
                    NOW(), LEAST(p_idle_exp, p_abs_exp), p_abs_exp, NULL, NOW()
                ) RETURNING user_sessions.id INTO v_sess_id;

                RETURN QUERY SELECT v_sess_id, p_public_id;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_create_session(VARCHAR, BIGINT, VARCHAR, BIGINT, VARCHAR, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_create_session(VARCHAR, BIGINT, VARCHAR, BIGINT, VARCHAR, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_create_session(VARCHAR, BIGINT, VARCHAR, BIGINT, VARCHAR, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ) TO untangle_auth;
            """
        )

        # 5. fn_auth_lookup_session
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_lookup_session(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS TABLE (
                session_id BIGINT,
                session_public_id VARCHAR(64),
                principal_id BIGINT,
                principal_public_id VARCHAR(64),
                principal_email VARCHAR(255),
                principal_display_name VARCHAR(255),
                active_organisation_id BIGINT,
                active_org_public_id VARCHAR(64),
                active_role_code VARCHAR(32),
                idle_expires_at TIMESTAMPTZ,
                absolute_expires_at TIMESTAMPTZ,
                last_active_at TIMESTAMPTZ,
                is_revoked BOOLEAN,
                is_stale BOOLEAN
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_s RECORD;
                v_is_revoked BOOLEAN;
                v_is_stale BOOLEAN := FALSE;
                v_role_code VARCHAR(32) := NULL;
                v_org_public_id VARCHAR(64) := NULL;
            BEGIN
                SELECT s.id AS s_id, s.public_id AS s_public_id, s.principal_id AS s_principal_id,
                       s.active_organisation_id AS s_active_org_id, s.membership_auth_version AS s_auth_ver,
                       s.idle_expires_at AS s_idle_exp, s.absolute_expires_at AS s_abs_exp,
                       s.last_active_at AS s_last_act, s.revoked_at AS s_revoked_at,
                       p.public_id AS p_public_id, p.email AS p_email, p.display_name AS p_display_name,
                       p.is_active AS p_is_active
                INTO v_s
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash;

                IF NOT FOUND THEN
                    RETURN;
                END IF;

                v_is_revoked := (
                    v_s.s_revoked_at IS NOT NULL OR
                    NOW() >= v_s.s_abs_exp OR
                    NOW() >= v_s.s_idle_exp OR
                    v_s.p_is_active = FALSE
                );

                IF v_s.s_active_org_id IS NOT NULL THEN
                    SELECT o.public_id, m.role_code, (m.status != 'active' OR o.is_active = FALSE OR m.auth_version != v_s.s_auth_ver)
                    INTO v_org_public_id, v_role_code, v_is_stale
                    FROM public.organisations o
                    LEFT JOIN public.organisation_memberships m ON m.organisation_id = o.id AND m.principal_id = v_s.s_principal_id
                    WHERE o.id = v_s.s_active_org_id;

                    IF NOT FOUND OR v_role_code IS NULL THEN
                        v_is_stale := TRUE;
                        v_role_code := NULL;
                    END IF;
                END IF;

                RETURN QUERY SELECT
                    v_s.s_id,
                    v_s.s_public_id,
                    v_s.s_principal_id,
                    v_s.p_public_id,
                    v_s.p_email,
                    v_s.p_display_name,
                    v_s.s_active_org_id,
                    v_org_public_id,
                    v_role_code,
                    v_s.s_idle_exp,
                    v_s.s_abs_exp,
                    v_s.s_last_act,
                    v_is_revoked,
                    v_is_stale;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_lookup_session(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_lookup_session(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_lookup_session(VARCHAR) TO untangle_app;
            """
        )

        # 6. fn_auth_touch_session_throttled
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_touch_session_throttled(
                p_session_token_hash VARCHAR(64),
                p_idle_window_seconds INT,
                p_throttle_seconds INT
            )
            RETURNS VOID
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                UPDATE public.user_sessions
                SET last_active_at = NOW(),
                    idle_expires_at = LEAST(NOW() + (p_idle_window_seconds || ' seconds')::interval, absolute_expires_at)
                WHERE session_token_hash = p_session_token_hash
                  AND revoked_at IS NULL
                  AND NOW() < absolute_expires_at
                  AND NOW() < idle_expires_at
                  AND last_active_at < NOW() - (p_throttle_seconds || ' seconds')::interval;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_touch_session_throttled(VARCHAR, INT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_touch_session_throttled(VARCHAR, INT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_touch_session_throttled(VARCHAR, INT, INT) TO untangle_app;
            """
        )

        # 7. fn_auth_revoke_session
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_revoke_session(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.user_sessions
                SET revoked_at = NOW()
                WHERE session_token_hash = p_session_token_hash
                  AND revoked_at IS NULL;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_revoke_session(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_revoke_session(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_revoke_session(VARCHAR) TO untangle_app;
            """
        )

        # 8. fn_auth_revoke_all_sessions
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_revoke_all_sessions(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS INT
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_principal_id BIGINT;
                v_rows INT := 0;
            BEGIN
                SELECT principal_id INTO v_principal_id
                FROM public.user_sessions
                WHERE session_token_hash = p_session_token_hash
                  AND revoked_at IS NULL
                  AND NOW() < absolute_expires_at
                  AND NOW() < idle_expires_at;

                IF NOT FOUND THEN
                    RETURN 0;
                END IF;

                UPDATE public.user_sessions
                SET revoked_at = NOW()
                WHERE principal_id = v_principal_id
                  AND revoked_at IS NULL;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_revoke_all_sessions(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_revoke_all_sessions(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_revoke_all_sessions(VARCHAR) TO untangle_app;
            """
        )

        # 9. fn_auth_switch_organisation
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_auth_switch_organisation(
                p_session_token_hash VARCHAR(64),
                p_target_org_id BIGINT,
                p_new_token_hash VARCHAR(64),
                p_idle_exp TIMESTAMPTZ,
                p_abs_exp TIMESTAMPTZ,
                p_audit_public_id VARCHAR(64)
            )
            RETURNS TABLE (new_auth_version INT, role_code VARCHAR(32))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_sess RECORD;
                v_auth_ver INT;
                v_role_code VARCHAR(32);
                v_org_public_id VARCHAR(64);
                v_prev_tenant VARCHAR(64);
            BEGIN
                SELECT s.id, s.principal_id, s.absolute_expires_at
                INTO v_sess
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unauthorized: invalid or expired session' USING ERRCODE = '42501';
                END IF;

                SELECT o.public_id, m.auth_version, m.role_code
                INTO v_org_public_id, v_auth_ver, v_role_code
                FROM public.organisations o
                JOIN public.organisation_memberships m ON m.organisation_id = o.id AND m.principal_id = v_sess.principal_id
                WHERE o.id = p_target_org_id AND o.is_active = TRUE AND m.status = 'active';

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Target organisation not found or no active membership' USING ERRCODE = '42501';
                END IF;

                UPDATE public.user_sessions
                SET active_organisation_id = p_target_org_id,
                    membership_auth_version = v_auth_ver,
                    session_token_hash = p_new_token_hash,
                    last_active_at = NOW(),
                    idle_expires_at = LEAST(p_idle_exp, v_sess.absolute_expires_at)
                WHERE id = v_sess.id;

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', p_target_org_id::text, true);
                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id, p_target_org_id, v_sess.principal_id,
                        'organisation.switched', 'organisation', v_org_public_id,
                        NULL, jsonb_build_object('role_code', v_role_code), NOW()
                    );
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN QUERY SELECT v_auth_ver, v_role_code;
            END;
            $$;
            ALTER FUNCTION public.fn_auth_switch_organisation(VARCHAR, BIGINT, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_auth_switch_organisation(VARCHAR, BIGINT, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_auth_switch_organisation(VARCHAR, BIGINT, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ, VARCHAR) TO untangle_app;
            """
        )

        # 10. fn_org_create
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_org_create(
                p_session_token_hash VARCHAR(64),
                p_org_name VARCHAR(255),
                p_org_public_id VARCHAR(64),
                p_membership_public_id VARCHAR(64),
                p_audit_public_id_1 VARCHAR(64),
                p_audit_public_id_2 VARCHAR(64)
            )
            RETURNS TABLE (org_id BIGINT, org_public_id VARCHAR(64))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_principal_id BIGINT;
                v_org_id BIGINT;
                v_prev_tenant VARCHAR(64);
            BEGIN
                SELECT s.principal_id INTO v_principal_id
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unauthorized: invalid or expired session' USING ERRCODE = '42501';
                END IF;

                INSERT INTO public.organisations (public_id, name, is_active, created_at, updated_at)
                VALUES (p_org_public_id, p_org_name, TRUE, NOW(), NOW())
                RETURNING id INTO v_org_id;

                INSERT INTO public.organisation_memberships (
                    public_id, organisation_id, principal_id, role_code, status, auth_version, created_at, updated_at
                ) VALUES (
                    p_membership_public_id, v_org_id, v_principal_id, 'owner', 'active', 1, NOW(), NOW()
                );

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', v_org_id::text, true);

                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id_1, v_org_id, v_principal_id,
                        'organisation.created', 'organisation', p_org_public_id,
                        NULL, jsonb_build_object('name', p_org_name), NOW()
                    );

                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id_2, v_org_id, v_principal_id,
                        'membership.assigned', 'organisation_membership', p_membership_public_id,
                        NULL, jsonb_build_object('role', 'owner'), NOW()
                    );

                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN QUERY SELECT v_org_id, p_org_public_id;
            END;
            $$;
            ALTER FUNCTION public.fn_org_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_org_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_org_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) TO untangle_app;
            """
        )

        # 11. fn_org_list
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_org_list(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS TABLE (
                org_id BIGINT,
                org_public_id VARCHAR(64),
                org_name VARCHAR(255),
                role_code VARCHAR(32),
                membership_status VARCHAR(32)
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_principal_id BIGINT;
            BEGIN
                SELECT s.principal_id INTO v_principal_id
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE;

                IF NOT FOUND THEN
                    RETURN;
                END IF;

                RETURN QUERY
                SELECT o.id, o.public_id, o.name, m.role_code, m.status
                FROM public.organisation_memberships m
                JOIN public.organisations o ON o.id = m.organisation_id
                WHERE m.principal_id = v_principal_id
                  AND o.is_active = TRUE
                ORDER BY o.name ASC;
            END;
            $$;
            ALTER FUNCTION public.fn_org_list(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_org_list(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_org_list(VARCHAR) TO untangle_app;
            """
        )

        # 12. fn_membership_list
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_membership_list(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS TABLE (
                membership_public_id VARCHAR(64),
                principal_public_id VARCHAR(64),
                email VARCHAR(255),
                display_name VARCHAR(255),
                role_code VARCHAR(32),
                status VARCHAR(32),
                auth_version INT,
                created_at TIMESTAMPTZ
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_sess RECORD;
            BEGIN
                SELECT s.active_organisation_id, s.principal_id
                INTO v_sess
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE;

                IF NOT FOUND OR v_sess.active_organisation_id IS NULL THEN
                    RAISE EXCEPTION 'Unauthorized: session not found or no active organisation' USING ERRCODE = '42501';
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM public.organisation_memberships
                    WHERE organisation_id = v_sess.active_organisation_id
                      AND principal_id = v_sess.principal_id
                      AND status = 'active'
                ) THEN
                    RAISE EXCEPTION 'Unauthorized: not an active member of organisation' USING ERRCODE = '42501';
                END IF;

                RETURN QUERY
                SELECT m.public_id, p.public_id, p.email, p.display_name, m.role_code, m.status, m.auth_version, m.created_at
                FROM public.organisation_memberships m
                JOIN public.principals p ON p.id = m.principal_id
                WHERE m.organisation_id = v_sess.active_organisation_id
                ORDER BY m.created_at ASC;
            END;
            $$;
            ALTER FUNCTION public.fn_membership_list(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_membership_list(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_membership_list(VARCHAR) TO untangle_app;
            """
        )

        # 13. fn_membership_mutate_with_mutex
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_membership_mutate_with_mutex(
                p_session_token_hash VARCHAR(64),
                p_target_principal_id BIGINT,
                p_new_role_code VARCHAR(32),
                p_new_status VARCHAR(32),
                p_audit_public_id VARCHAR(64)
            )
            RETURNS TABLE (membership_id BIGINT, updated_role VARCHAR(32), updated_status VARCHAR(32), new_auth_version INT)
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_actor_principal_id BIGINT;
                v_organisation_id BIGINT;
                v_actor_role VARCHAR(32);
                v_active_owners INT;
                v_target_existing_id BIGINT;
                v_target_public_id VARCHAR(64);
                v_target_current_role VARCHAR(32);
                v_target_current_status VARCHAR(32);
                v_new_auth_version INT;
                v_prev_tenant VARCHAR(64);
            BEGIN
                SELECT s.active_organisation_id INTO v_organisation_id
                FROM public.user_sessions s
                WHERE s.session_token_hash = p_session_token_hash;

                IF v_organisation_id IS NULL THEN
                    RAISE EXCEPTION 'Unauthorized: session not found or no active organisation' USING ERRCODE = '42501';
                END IF;

                PERFORM id FROM public.organisations WHERE id = v_organisation_id FOR UPDATE;

                SELECT s.principal_id, m.role_code
                INTO v_actor_principal_id, v_actor_role
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                JOIN public.organisations o ON o.id = s.active_organisation_id
                JOIN public.organisation_memberships m ON m.organisation_id = s.active_organisation_id 
                                                    AND m.principal_id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE
                  AND o.is_active = TRUE
                  AND m.status = 'active'
                  AND s.membership_auth_version = m.auth_version;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unauthorized: invalid, expired, or stale session' USING ERRCODE = '42501';
                END IF;

                IF v_actor_role NOT IN ('owner', 'admin') THEN
                    RAISE EXCEPTION 'Forbidden: only owners and admins may modify memberships' USING ERRCODE = '42501';
                END IF;

                IF v_actor_principal_id = p_target_principal_id THEN
                    RAISE EXCEPTION 'Forbidden: users cannot modify their own membership role or status' USING ERRCODE = '42501';
                END IF;

                SELECT id, public_id, role_code, status, auth_version
                INTO v_target_existing_id, v_target_public_id, v_target_current_role, v_target_current_status, v_new_auth_version
                FROM public.organisation_memberships
                WHERE organisation_id = v_organisation_id AND principal_id = p_target_principal_id;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Target member not found in organisation' USING ERRCODE = 'P0002';
                END IF;

                IF v_actor_role = 'admin' AND (v_target_current_role = 'owner' OR p_new_role_code = 'owner') THEN
                    RAISE EXCEPTION 'Forbidden: administrators cannot alter or assign owner roles' USING ERRCODE = '42501';
                END IF;

                IF v_target_current_role = 'owner' AND v_target_current_status = 'active' 
                   AND (p_new_role_code != 'owner' OR p_new_status != 'active') THEN
                    SELECT COUNT(*) INTO v_active_owners
                    FROM public.organisation_memberships
                    WHERE organisation_id = v_organisation_id AND role_code = 'owner' AND status = 'active';

                    IF v_active_owners <= 1 THEN
                        RAISE EXCEPTION 'Cannot demote or remove the last active owner of organisation %', v_organisation_id
                            USING ERRCODE = 'P0003';
                    END IF;
                END IF;

                v_new_auth_version := v_new_auth_version + 1;
                UPDATE public.organisation_memberships
                SET role_code = p_new_role_code, status = p_new_status, auth_version = v_new_auth_version, updated_at = NOW()
                WHERE id = v_target_existing_id;

                UPDATE public.user_sessions
                SET revoked_at = NOW()
                WHERE principal_id = p_target_principal_id 
                  AND active_organisation_id = v_organisation_id 
                  AND revoked_at IS NULL;

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', v_organisation_id::text, true);
                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id, v_organisation_id, v_actor_principal_id,
                        CASE WHEN p_new_status != 'active' THEN 'membership.suspended' ELSE 'membership.role_changed' END,
                        'organisation_membership', v_target_public_id, NULL,
                        jsonb_build_object('target_principal_id', p_target_principal_id, 'previous_role', v_target_current_role, 'new_role', p_new_role_code),
                        NOW()
                    );
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN QUERY SELECT v_target_existing_id, p_new_role_code, p_new_status, v_new_auth_version;
            END;
            $$;
            ALTER FUNCTION public.fn_membership_mutate_with_mutex(VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_membership_mutate_with_mutex(VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_membership_mutate_with_mutex(VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR) TO untangle_app;
            """
        )

        # 14. fn_invitation_create
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_invitation_create(
                p_session_token_hash VARCHAR(64),
                p_email VARCHAR(255),
                p_role_code VARCHAR(32),
                p_token_hash VARCHAR(64),
                p_invitation_public_id VARCHAR(64),
                p_audit_public_id VARCHAR(64),
                p_expires_at TIMESTAMPTZ
            )
            RETURNS TABLE (invitation_id BIGINT, invitation_public_id VARCHAR(64))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_actor RECORD;
                v_norm_email VARCHAR(255);
                v_inv_id BIGINT;
                v_prev_tenant VARCHAR(64);
            BEGIN
                v_norm_email := lower(trim(p_email));

                SELECT s.active_organisation_id, s.principal_id, m.role_code
                INTO v_actor
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                JOIN public.organisation_memberships m ON m.organisation_id = s.active_organisation_id AND m.principal_id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE
                  AND m.status = 'active';

                IF NOT FOUND OR v_actor.active_organisation_id IS NULL THEN
                    RAISE EXCEPTION 'Unauthorized: session not found or no active organisation' USING ERRCODE = '42501';
                END IF;

                IF v_actor.role_code NOT IN ('owner', 'admin') THEN
                    RAISE EXCEPTION 'Forbidden: only owners and admins may invite members' USING ERRCODE = '42501';
                END IF;

                IF v_actor.role_code = 'admin' AND p_role_code = 'owner' THEN
                    RAISE EXCEPTION 'Forbidden: administrators cannot invite owners' USING ERRCODE = '42501';
                END IF;

                IF NOT EXISTS (SELECT 1 FROM public.roles WHERE code = p_role_code) THEN
                    RAISE EXCEPTION 'Invalid role code: %', p_role_code USING ERRCODE = '42501';
                END IF;

                IF EXISTS (
                    SELECT 1 FROM public.organisation_memberships m
                    JOIN public.principals p ON p.id = m.principal_id
                    WHERE m.organisation_id = v_actor.active_organisation_id
                      AND lower(p.email) = v_norm_email
                      AND m.status = 'active'
                ) THEN
                    RAISE EXCEPTION 'User with email % is already an active member of this organisation', p_email USING ERRCODE = 'P0006';
                END IF;

                INSERT INTO public.organisation_invitations (
                    public_id, organisation_id, invited_by_principal_id, email,
                    role_code, token_hash, status, expires_at, created_at, updated_at
                ) VALUES (
                    p_invitation_public_id, v_actor.active_organisation_id, v_actor.principal_id,
                    v_norm_email, p_role_code, p_token_hash, 'pending', p_expires_at, NOW(), NOW()
                ) RETURNING id INTO v_inv_id;

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', v_actor.active_organisation_id::text, true);
                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id, v_actor.active_organisation_id, v_actor.principal_id,
                        'invitation.created', 'organisation_invitation', p_invitation_public_id,
                        NULL, jsonb_build_object('role', p_role_code), NOW()
                    );
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN QUERY SELECT v_inv_id, p_invitation_public_id;
            END;
            $$;
            ALTER FUNCTION public.fn_invitation_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMPTZ) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_invitation_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMPTZ) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_invitation_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMPTZ) TO untangle_app;
            """
        )

        # 15. fn_invitation_lookup
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_invitation_lookup(
                p_token_hash VARCHAR(64)
            )
            RETURNS TABLE (
                invitation_id BIGINT,
                invitation_public_id VARCHAR(64),
                organisation_name VARCHAR(255),
                email VARCHAR(255),
                role_code VARCHAR(32),
                status VARCHAR(32),
                is_expired BOOLEAN
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                RETURN QUERY
                SELECT i.id, i.public_id, o.name, i.email, i.role_code, i.status, (NOW() >= i.expires_at)
                FROM public.organisation_invitations i
                JOIN public.organisations o ON o.id = i.organisation_id
                WHERE i.token_hash = p_token_hash;
            END;
            $$;
            ALTER FUNCTION public.fn_invitation_lookup(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_invitation_lookup(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_invitation_lookup(VARCHAR) TO untangle_app;
            """
        )

        # 16. fn_invitation_accept_with_mutex
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_invitation_accept_with_mutex(
                p_session_token_hash VARCHAR(64),
                p_token_hash VARCHAR(64),
                p_membership_public_id VARCHAR(64),
                p_audit_public_id_1 VARCHAR(64),
                p_audit_public_id_2 VARCHAR(64)
            )
            RETURNS TABLE (membership_id BIGINT, organisation_id BIGINT, role_code VARCHAR(32))
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_caller RECORD;
                v_inv RECORD;
                v_mem_id BIGINT;
                v_prev_tenant VARCHAR(64);
            BEGIN
                SELECT s.principal_id, p.email
                INTO v_caller
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unauthorized: invalid or expired session' USING ERRCODE = '42501';
                END IF;

                SELECT id, public_id, organisation_id, email, role_code, status, expires_at
                INTO v_inv
                FROM public.organisation_invitations
                WHERE token_hash = p_token_hash;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Invitation not found' USING ERRCODE = 'P0002';
                END IF;

                IF v_inv.status != 'pending' OR NOW() >= v_inv.expires_at THEN
                    RAISE EXCEPTION 'Invitation is no longer pending or has expired' USING ERRCODE = 'P0002';
                END IF;

                IF lower(trim(v_inv.email)) != lower(trim(v_caller.email)) THEN
                    RAISE EXCEPTION 'Invitation email does not match authenticated user' USING ERRCODE = 'P0005';
                END IF;

                PERFORM id FROM public.organisations WHERE id = v_inv.organisation_id FOR UPDATE;

                UPDATE public.organisation_invitations
                SET status = 'accepted', accepted_at = NOW(), updated_at = NOW()
                WHERE id = v_inv.id;

                INSERT INTO public.organisation_memberships (
                    public_id, organisation_id, principal_id, role_code, status, auth_version, created_at, updated_at
                ) VALUES (
                    p_membership_public_id, v_inv.organisation_id, v_caller.principal_id, v_inv.role_code, 'active', 1, NOW(), NOW()
                ) RETURNING id INTO v_mem_id;

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', v_inv.organisation_id::text, true);

                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id_1, v_inv.organisation_id, v_caller.principal_id,
                        'invitation.accepted', 'organisation_invitation', v_inv.public_id,
                        NULL, jsonb_build_object('accepted_by_principal_id', v_caller.principal_id), NOW()
                    );

                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id_2, v_inv.organisation_id, v_caller.principal_id,
                        'membership.assigned', 'organisation_membership', p_membership_public_id,
                        NULL, jsonb_build_object('role', v_inv.role_code), NOW()
                    );

                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN QUERY SELECT v_mem_id, v_inv.organisation_id, v_inv.role_code;
            END;
            $$;
            ALTER FUNCTION public.fn_invitation_accept_with_mutex(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_invitation_accept_with_mutex(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_invitation_accept_with_mutex(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR) TO untangle_app;
            """
        )

        # 17. fn_invitation_revoke
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_invitation_revoke(
                p_session_token_hash VARCHAR(64),
                p_invitation_public_id VARCHAR(64),
                p_audit_public_id VARCHAR(64)
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_actor RECORD;
                v_inv RECORD;
                v_rows INT;
                v_prev_tenant VARCHAR(64);
            BEGIN
                SELECT s.active_organisation_id, s.principal_id, m.role_code
                INTO v_actor
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                JOIN public.organisation_memberships m ON m.organisation_id = s.active_organisation_id AND m.principal_id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE
                  AND m.status = 'active';

                IF NOT FOUND OR v_actor.active_organisation_id IS NULL THEN
                    RAISE EXCEPTION 'Unauthorized: session not found or no active organisation' USING ERRCODE = '42501';
                END IF;

                IF v_actor.role_code NOT IN ('owner', 'admin') THEN
                    RAISE EXCEPTION 'Forbidden: only owners and admins may revoke invitations' USING ERRCODE = '42501';
                END IF;

                SELECT id, organisation_id, public_id, status
                INTO v_inv
                FROM public.organisation_invitations
                WHERE public_id = p_invitation_public_id;

                IF NOT FOUND OR v_inv.organisation_id != v_actor.active_organisation_id THEN
                    RETURN FALSE;
                END IF;

                UPDATE public.organisation_invitations
                SET status = 'revoked', revoked_at = NOW(), updated_at = NOW()
                WHERE id = v_inv.id AND status = 'pending';
                GET DIAGNOSTICS v_rows = ROW_COUNT;

                IF v_rows = 0 THEN
                    RETURN FALSE;
                END IF;

                v_prev_tenant := current_setting('app.current_tenant_id', true);
                BEGIN
                    PERFORM set_config('app.current_tenant_id', v_inv.organisation_id::text, true);
                    INSERT INTO public.audit_events (
                        public_id, organisation_id, actor_principal_id, event_type,
                        subject_type, subject_public_id, request_id, metadata_json, created_at
                    ) VALUES (
                        p_audit_public_id, v_inv.organisation_id, v_actor.principal_id,
                        'invitation.revoked', 'organisation_invitation', v_inv.public_id,
                        NULL, '{}'::jsonb, NOW()
                    );
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                EXCEPTION WHEN OTHERS THEN
                    IF v_prev_tenant IS NULL THEN PERFORM set_config('app.current_tenant_id', '', true);
                    ELSE PERFORM set_config('app.current_tenant_id', v_prev_tenant, true); END IF;
                    RAISE;
                END;

                RETURN TRUE;
            END;
            $$;
            ALTER FUNCTION public.fn_invitation_revoke(VARCHAR, VARCHAR, VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_invitation_revoke(VARCHAR, VARCHAR, VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_invitation_revoke(VARCHAR, VARCHAR, VARCHAR) TO untangle_app;
            """
        )

        # 18. fn_invitation_list
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_invitation_list(
                p_session_token_hash VARCHAR(64)
            )
            RETURNS TABLE (
                invitation_public_id VARCHAR(64),
                email VARCHAR(255),
                role_code VARCHAR(32),
                status VARCHAR(32),
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_actor RECORD;
            BEGIN
                SELECT s.active_organisation_id, s.principal_id, m.role_code
                INTO v_actor
                FROM public.user_sessions s
                JOIN public.principals p ON p.id = s.principal_id
                JOIN public.organisation_memberships m ON m.organisation_id = s.active_organisation_id AND m.principal_id = s.principal_id
                WHERE s.session_token_hash = p_session_token_hash
                  AND s.revoked_at IS NULL
                  AND NOW() < s.absolute_expires_at
                  AND NOW() < s.idle_expires_at
                  AND p.is_active = TRUE
                  AND m.status = 'active';

                IF NOT FOUND OR v_actor.active_organisation_id IS NULL THEN
                    RAISE EXCEPTION 'Unauthorized: session not found or no active organisation' USING ERRCODE = '42501';
                END IF;

                IF v_actor.role_code NOT IN ('owner', 'admin') THEN
                    RAISE EXCEPTION 'Forbidden: only owners and admins may view invitations' USING ERRCODE = '42501';
                END IF;

                RETURN QUERY
                SELECT i.public_id, i.email, i.role_code, i.status, i.expires_at, i.created_at
                FROM public.organisation_invitations i
                WHERE i.organisation_id = v_actor.active_organisation_id
                ORDER BY i.created_at DESC;
            END;
            $$;
            ALTER FUNCTION public.fn_invitation_list(VARCHAR) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_invitation_list(VARCHAR) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_invitation_list(VARCHAR) TO untangle_app;
            """
        )

        # 19. fn_sec_event_record (Granted to BOTH untangle_auth and untangle_app)
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_sec_event_record(
                p_public_id VARCHAR(64),
                p_event_type VARCHAR(64),
                p_actor_principal_id BIGINT,
                p_subject_type VARCHAR(64),
                p_subject_identifier VARCHAR(255),
                p_ip_hash VARCHAR(64),
                p_user_agent_truncated VARCHAR(128),
                p_details_json JSONB
            )
            RETURNS VOID
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                IF length(p_subject_identifier) > 255 THEN
                    RAISE EXCEPTION 'subject_identifier exceeds 255 characters' USING ERRCODE = '22001';
                END IF;

                INSERT INTO public.control_plane_security_events (
                    public_id, event_type, actor_principal_id, subject_type,
                    subject_identifier, ip_hash, user_agent_truncated, details_json, created_at
                ) VALUES (
                    p_public_id, p_event_type, p_actor_principal_id, p_subject_type,
                    p_subject_identifier, p_ip_hash, p_user_agent_truncated, coalesce(p_details_json, '{}'::jsonb), NOW()
                );
            END;
            $$;
            ALTER FUNCTION public.fn_sec_event_record(VARCHAR, VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR, VARCHAR, JSONB) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_sec_event_record(VARCHAR, VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR, VARCHAR, JSONB) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_sec_event_record(VARCHAR, VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR, VARCHAR, JSONB) TO untangle_auth, untangle_app;
            """
        )

        # 20. fn_maintenance_purge_security_events
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_maintenance_purge_security_events(
                p_retention_days INT DEFAULT 90
            )
            RETURNS INT
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                DELETE FROM public.control_plane_security_events
                WHERE created_at < NOW() - (p_retention_days || ' days')::interval;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows;
            END;
            $$;
            ALTER FUNCTION public.fn_maintenance_purge_security_events(INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_maintenance_purge_security_events(INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_maintenance_purge_security_events(INT) TO untangle_maintenance;
            """
        )

        # 21. fn_maintenance_purge_oidc_transactions
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_maintenance_purge_oidc_transactions(
                p_retention_hours INT DEFAULT 1
            )
            RETURNS INT
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                DELETE FROM public.oidc_auth_transactions
                WHERE created_at < NOW() - (p_retention_hours || ' hours')::interval
                   OR consumed_at IS NOT NULL;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows;
            END;
            $$;
            ALTER FUNCTION public.fn_maintenance_purge_oidc_transactions(INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_maintenance_purge_oidc_transactions(INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_maintenance_purge_oidc_transactions(INT) TO untangle_maintenance;
            """
        )

        # 22. fn_maintenance_purge_expired_sessions
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_maintenance_purge_expired_sessions(
                p_retention_days INT DEFAULT 30
            )
            RETURNS INT
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                DELETE FROM public.user_sessions
                WHERE (revoked_at IS NOT NULL AND revoked_at < NOW() - (p_retention_days || ' days')::interval)
                   OR (absolute_expires_at < NOW() - (p_retention_days || ' days')::interval);
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows;
            END;
            $$;
            ALTER FUNCTION public.fn_maintenance_purge_expired_sessions(INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_maintenance_purge_expired_sessions(INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_maintenance_purge_expired_sessions(INT) TO untangle_maintenance;
            """
        )

        # 23. fn_maintenance_redact_accepted_invitations
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_maintenance_redact_accepted_invitations(
                p_retention_days INT DEFAULT 14
            )
            RETURNS INT
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.organisation_invitations
                SET email = 'redacted@untangle.internal', updated_at = NOW()
                WHERE status IN ('accepted', 'revoked')
                  AND (
                      (accepted_at IS NOT NULL AND accepted_at < NOW() - (p_retention_days || ' days')::interval)
                      OR (revoked_at IS NOT NULL AND revoked_at < NOW() - (p_retention_days || ' days')::interval)
                  )
                  AND email != 'redacted@untangle.internal';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows;
            END;
            $$;
            ALTER FUNCTION public.fn_maintenance_redact_accepted_invitations(INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_maintenance_redact_accepted_invitations(INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_maintenance_redact_accepted_invitations(INT) TO untangle_maintenance;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # Drop 23 functions
        op.execute("DROP FUNCTION IF EXISTS public.fn_maintenance_redact_accepted_invitations(INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_maintenance_purge_expired_sessions(INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_maintenance_purge_oidc_transactions(INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_maintenance_purge_security_events(INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_sec_event_record(VARCHAR, VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR, VARCHAR, JSONB);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_invitation_list(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_invitation_revoke(VARCHAR, VARCHAR, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_invitation_accept_with_mutex(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_invitation_lookup(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_invitation_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMPTZ);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_membership_mutate_with_mutex(VARCHAR, BIGINT, VARCHAR, VARCHAR, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_membership_list(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_org_list(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_org_create(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_switch_organisation(VARCHAR, BIGINT, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_revoke_all_sessions(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_revoke_session(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_touch_session_throttled(VARCHAR, INT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_lookup_session(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_create_session(VARCHAR, BIGINT, VARCHAR, BIGINT, VARCHAR, VARCHAR, TIMESTAMPTZ, TIMESTAMPTZ);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_auth_resolve_federated_identity(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_oidc_consume_transaction(VARCHAR);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_oidc_create_transaction(VARCHAR, VARCHAR, VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ);")

        op.execute("DROP POLICY IF EXISTS fn_owner_audit_insert_policy ON public.audit_events;")

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("chk_audit_events_type_allowed", type_="check")
        batch_op.drop_constraint("chk_audit_events_subject_allowed", type_="check")
        batch_op.create_check_constraint(
            "chk_audit_events_type_allowed",
            "event_type IN ('run.initiated', 'run.completed', 'run.failed', 'certificate.issued', 'membership.assigned', 'organisation.deactivated')",
        )
        batch_op.create_check_constraint(
            "chk_audit_events_subject_allowed",
            "subject_type IN ('reconciliation_run', 'certificate', 'organisation_membership', 'organisation')",
        )

    with op.batch_alter_table("organisation_memberships") as batch_op:
        if is_postgres:
            batch_op.drop_constraint("chk_memberships_auth_version_positive", type_="check")
        batch_op.drop_column("auth_version")

    op.drop_table("control_plane_security_events")
    op.drop_table("organisation_invitations")
    op.drop_table("user_sessions")
    op.drop_table("oidc_auth_transactions")
    op.drop_table("federated_identities")
    op.drop_table("trusted_auth_issuers")

"""Initial multi-tenant schema with composite constraints, RLS, and immutability triggers.

Revision ID: 0001_initial_tenant_schema
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_initial_tenant_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Machine-readable provenance. The actor and timestamp are derived from the Git commit that
# introduced this migration; the source identifies the approved Phase 1 architecture document.
MIGRATION_PROVENANCE: dict[str, str] = {
    "created_by": "vinayaksonthalia",
    "created_at": "2026-09-05T03:44:44Z",
    "source": "docs/PERSISTENCE_AND_TENANT_ISOLATION.md#entity--ownership-model",
}

# Cross-dialect JSON type: JSONB on PostgreSQL, JSON on SQLite
JSONType = sa.JSON().with_variant(JSONB, "postgresql")

TENANT_TABLES = [
    "reconciliation_runs",
    "uploaded_file_metadata",
    "reconciliation_results",
    "investigations",
    "certificates",
    "artifact_metadata",
    "audit_events",
]


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

    # 1. organisations
    op.create_table(
        "organisations",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="organisations_public_id_key"),
        sa.CheckConstraint(
            "(is_active = true AND deleted_at IS NULL) OR (is_active = false AND deleted_at IS NOT NULL)",
            name="chk_org_active_deleted",
        ),
    )
    op.create_index("ix_organisations_public_id", "organisations", ["public_id"])

    # 2. principals
    op.create_table(
        "principals",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("external_subject_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="principals_public_id_key"),
        sa.CheckConstraint(
            "(is_active = true AND deleted_at IS NULL) OR (is_active = false AND deleted_at IS NOT NULL)",
            name="chk_principal_active_deleted",
        ),
    )
    op.create_index("ix_principals_public_id", "principals", ["public_id"])

    # 3. roles
    op.create_table(
        "roles",
        pk_id_column(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code", name="roles_code_key"),
        sa.CheckConstraint(
            "code IN ('owner', 'admin', 'operator', 'reviewer', 'auditor')",
            name="chk_roles_code_allowed",
        ),
    )

    # Seed authoritative roles
    roles_table = sa.table(
        "roles",
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        roles_table,
        [
            {"code": "owner", "description": "Full organisation owner"},
            {"code": "admin", "description": "Organisation administrator"},
            {"code": "operator", "description": "Operations and reconciliation preparer"},
            {"code": "reviewer", "description": "Reconciliation reviewer and approver"},
            {"code": "auditor", "description": "Read-only compliance auditor"},
        ],
    )

    # 4. organisation_memberships
    op.create_table(
        "organisation_memberships",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role_code", sa.String(32), sa.ForeignKey("roles.code"), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="organisation_memberships_public_id_key"),
        sa.UniqueConstraint("organisation_id", "principal_id", name="uq_memberships_org_principal"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'invited')",
            name="chk_memberships_status_allowed",
        ),
    )
    op.create_index("ix_memberships_org_id", "organisation_memberships", ["organisation_id"])
    op.create_index("ix_memberships_principal_id", "organisation_memberships", ["principal_id"])
    op.create_index("ix_memberships_public_id", "organisation_memberships", ["public_id"])

    # 5. reconciliation_runs
    op.create_table(
        "reconciliation_runs",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="initiated", nullable=False),
        sa.Column("reconciliation_hash", sa.String(64), nullable=True),
        sa.Column("bank_statement_hash", sa.String(64), nullable=True),
        sa.Column("recon_report_hash", sa.String(64), nullable=True),
        sa.Column("order_ledger_hash", sa.String(64), nullable=True),
        sa.Column("evidence_pack_id", sa.String(128), nullable=True),
        sa.Column("evidence_pack_version", sa.String(64), nullable=True),
        sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.String(255), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="reconciliation_runs_public_id_key"),
        sa.UniqueConstraint("organisation_id", "id", name="uq_reconciliation_runs_org_id"),
        sa.CheckConstraint(
            "status IN ('initiated', 'running', 'completed', 'failed', 'aborted')",
            name="chk_runs_status_allowed",
        ),
        sa.CheckConstraint(
            "("
            "(status = 'initiated' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at >= started_at AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL AND error_code IS NOT NULL) OR "
            "(status = 'aborted' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL)"
            ")",
            name="chk_runs_lifecycle_state_machine",
        ),
        sa.CheckConstraint(
            "(is_deleted = false AND deleted_at IS NULL) OR (is_deleted = true AND deleted_at IS NOT NULL)",
            name="chk_runs_soft_delete_consistency",
        ),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "reconciliation_hash", 64, nullable=True),
            name="chk_runs_recon_hash_hex",
        ),
    )
    op.create_index("ix_runs_org_id", "reconciliation_runs", ["organisation_id"])
    op.create_index("ix_runs_public_id", "reconciliation_runs", ["public_id"])
    op.create_index("ix_runs_started_at", "reconciliation_runs", ["started_at"])

    # 6. uploaded_file_metadata
    op.create_table(
        "uploaded_file_metadata",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("file_role", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="uploaded_file_metadata_public_id_key"),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_uploaded_files_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_uploaded_files_org",
        ),
        sa.UniqueConstraint(
            "organisation_id", "run_id", "file_role", name="uq_uploaded_files_run_role"
        ),
        sa.CheckConstraint(
            "file_role IN ('bank_statement', 'recon_report', 'order_ledger')",
            name="chk_uploaded_files_role_allowed",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="chk_uploaded_files_size_nonnegative"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "sha256_checksum", 64, nullable=False),
            name="chk_uploaded_files_sha256_hex",
        ),
    )
    op.create_index("ix_uploaded_files_org_id", "uploaded_file_metadata", ["organisation_id"])
    op.create_index("ix_uploaded_files_run_id", "uploaded_file_metadata", ["run_id"])
    op.create_index("ix_uploaded_files_public_id", "uploaded_file_metadata", ["public_id"])

    # 7. reconciliation_results
    op.create_table(
        "reconciliation_results",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_json", JSONType, nullable=False),
        sa.Column("presentation_json", JSONType, nullable=False),
        sa.Column("canonical_report_text", sa.Text(), nullable=False),
        sa.Column("audit_root", sa.String(64), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="reconciliation_results_public_id_key"),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_results_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_results_org",
        ),
        sa.UniqueConstraint("organisation_id", "run_id", name="uq_results_org_run"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "audit_root", 64, nullable=False),
            name="chk_results_audit_root_hex",
        ),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "report_sha256", 64, nullable=False),
            name="chk_results_report_sha256_hex",
        ),
    )
    op.create_index("ix_results_org_id", "reconciliation_results", ["organisation_id"])
    op.create_index("ix_results_run_id", "reconciliation_results", ["run_id"])
    op.create_index("ix_results_public_id", "reconciliation_results", ["public_id"])

    # 8. investigations
    op.create_table(
        "investigations",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("line_key", sa.String(64), nullable=False),
        sa.Column("root_cause", sa.String(64), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("variance_paise", sa.BigInteger(), nullable=False),
        sa.Column("details_json", JSONType, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="investigations_public_id_key"),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_investigations_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_investigations_org",
        ),
        sa.UniqueConstraint(
            "organisation_id", "run_id", "line_key", name="uq_investigations_org_run_line"
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="chk_investigations_confidence_bounds",
        ),
        sa.CheckConstraint(
            "root_cause IN ("
            "'mdr_fee_drift', 'cross_cycle_refund_lag', 'on_hold_release', "
            "'dispute_deduction', 'partial_capture', 'bank_charge_or_rounding', "
            "'rolling_reserve', 'unexplained'"
            ")",
            name="chk_investigations_root_cause_allowed",
        ),
    )
    op.create_index("ix_investigations_org_id", "investigations", ["organisation_id"])
    op.create_index("ix_investigations_run_id", "investigations", ["run_id"])
    op.create_index("ix_investigations_public_id", "investigations", ["public_id"])

    # 9. certificates
    op.create_table(
        "certificates",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("is_signed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("public_key_pem", sa.Text(), nullable=True),
        sa.Column("certificate_json", JSONType, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="certificates_public_id_key"),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_certificates_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_certificates_org",
        ),
        sa.UniqueConstraint("organisation_id", "run_id", name="uq_certificates_org_run"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "content_sha256", 64, nullable=False),
            name="chk_certificates_content_sha256_hex",
        ),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "report_sha256", 64, nullable=False),
            name="chk_certificates_report_sha256_hex",
        ),
        sa.CheckConstraint(
            "("
            "(is_signed = false AND signature IS NULL AND public_key_pem IS NULL) OR "
            "(is_signed = true AND signature IS NOT NULL AND public_key_pem IS NOT NULL)"
            ")",
            name="chk_certificates_signature_consistency",
        ),
    )
    op.create_index("ix_certificates_org_id", "certificates", ["organisation_id"])
    op.create_index("ix_certificates_run_id", "certificates", ["run_id"])
    op.create_index("ix_certificates_public_id", "certificates", ["public_id"])

    # 10. artifact_metadata
    op.create_table(
        "artifact_metadata",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("organisation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="artifact_metadata_public_id_key"),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_artifacts_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="RESTRICT",
            name="fk_artifacts_org",
        ),
        sa.UniqueConstraint(
            "organisation_id", "run_id", "artifact_type", name="uq_artifacts_org_run_type"
        ),
        sa.CheckConstraint(
            "artifact_type IN ('tally_xml', 'report_json', 'certificate_json')",
            name="chk_artifacts_type_allowed",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="chk_artifacts_size_nonnegative"),
        sa.CheckConstraint(
            hex_hash_check_sql(is_postgres, "content_sha256", 64, nullable=False),
            name="chk_artifacts_content_sha256_hex",
        ),
    )
    op.create_index("ix_artifacts_org_id", "artifact_metadata", ["organisation_id"])
    op.create_index("ix_artifacts_run_id", "artifact_metadata", ["run_id"])
    op.create_index("ix_artifacts_public_id", "artifact_metadata", ["public_id"])

    # 11. audit_events
    op.create_table(
        "audit_events",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_public_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", JSONType, server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="audit_events_public_id_key"),
        sa.CheckConstraint(
            "event_type IN ('run.initiated', 'run.completed', 'run.failed', 'certificate.issued', 'membership.assigned', 'organisation.deactivated')",
            name="chk_audit_events_type_allowed",
        ),
        sa.CheckConstraint(
            "subject_type IN ('reconciliation_run', 'certificate', 'organisation_membership', 'organisation')",
            name="chk_audit_events_subject_allowed",
        ),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["organisation_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_public_id", "audit_events", ["public_id"])

    # -----------------------------------------------------------------------
    # PostgreSQL-Specific: RLS Policies and Immutability Triggers
    # -----------------------------------------------------------------------
    if is_postgres:
        # The runtime role verifies the schema revision during application startup.  It needs
        # only read access to Alembic's bookkeeping table; all DDL remains migration-role-only.
        op.execute("GRANT SELECT ON TABLE alembic_version TO untangle_app")

        # Grant the runtime application role its table-level DML here, after the tables exist.
        # scripts/provision_db_roles.sql runs BEFORE the first migration (the documented order),
        # so it cannot grant these; issuing them here makes a fresh database correct on its own.
        # Row-Level Security still constrains which rows the role can touch. Immutable ledgers
        # get SELECT/INSERT only; UPDATE and DELETE stay ungranted and are trigger-blocked below.
        for _crud_table in (
            "reconciliation_runs",
            "uploaded_file_metadata",
            "investigations",
            "artifact_metadata",
        ):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_crud_table} TO untangle_app")
        for _append_only_table in ("reconciliation_results", "certificates", "audit_events"):
            op.execute(f"GRANT SELECT, INSERT ON {_append_only_table} TO untangle_app")

        # Create immutability trigger function raising SQLSTATE P0001
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trg_prevent_record_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Table % is immutable: UPDATE and DELETE operations are prohibited', TG_TABLE_NAME
                    USING ERRCODE = 'P0001';
            END;
            $$ LANGUAGE plpgsql;
            """
        )

        # Attach immutability triggers to audit_events, certificates, and reconciliation_results
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_immutable
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();

            CREATE TRIGGER trg_certificates_immutable
            BEFORE UPDATE OR DELETE ON certificates
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();

            CREATE TRIGGER trg_results_immutable
            BEFORE UPDATE OR DELETE ON reconciliation_results
            FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();
            """
        )

        # Enable RLS on all tenant data tables and apply permissive tenant_isolation_policy
        for table in TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_policy ON {table}
                    FOR ALL
                    TO untangle_app
                    USING (organisation_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
                    WITH CHECK (organisation_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint);
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        for table in reversed(TENANT_TABLES):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;")
        op.execute("DROP TRIGGER IF EXISTS trg_certificates_immutable ON certificates;")
        op.execute("DROP TRIGGER IF EXISTS trg_results_immutable ON reconciliation_results;")
        op.execute("DROP FUNCTION IF EXISTS trg_prevent_record_mutation();")

    op.drop_table("audit_events")
    op.drop_table("artifact_metadata")
    op.drop_table("certificates")
    op.drop_table("investigations")
    op.drop_table("reconciliation_results")
    op.drop_table("uploaded_file_metadata")
    op.drop_table("reconciliation_runs")
    op.drop_table("organisation_memberships")
    op.drop_table("roles")
    op.drop_table("principals")
    op.drop_table("organisations")

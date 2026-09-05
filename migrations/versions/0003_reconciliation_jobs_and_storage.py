"""Durable reconciliation jobs, idempotency records, S3 storage metadata, and worker functions.

Revision ID: 0003_reconciliation_jobs_and_storage
Revises: 0002_auth_federation_sessions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0003_reconciliation_jobs_and_storage"
down_revision: str | None = "0002_auth_federation_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATION_PROVENANCE: dict[str, str] = {
    "created_by": "vinayaksonthalia",
    "created_at": "2026-09-05T19:45:00Z",
    "source": "docs/PRODUCT_COMPLETION_ROADMAP.md#phase-3--saved-runs-and-multi-month-workspace",
}

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def pk_id_column() -> sa.Column:
    """Dialect-portable primary key ID column (BigInteger on Postgres, Integer on SQLite)."""
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # The revision id is 33 characters long, while Alembic's bootstrap table
    # in older installs used VARCHAR(32).  Widen it before Alembic records this
    # revision, otherwise an otherwise valid migration fails at commit time.
    if is_postgres:
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(32),
            type_=sa.String(128),
        )
    elif bind.dialect.name == "sqlite":
        with op.batch_alter_table("alembic_version") as batch_op:
            batch_op.alter_column(
                "version_num", existing_type=sa.String(32), type_=sa.String(128)
            )

    # 1. Extend reconciliation_runs with reporting periods, legal hold, and provenance
    with op.batch_alter_table("reconciliation_runs") as batch_op:
        batch_op.add_column(sa.Column("reporting_period_start", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("reporting_period_end", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("legal_hold", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("engine_version", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("rule_pack_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("rule_pack_version", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("bank_adapter_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("bank_adapter_version", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "parent_run_id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT", name="fk_runs_parent_run_id"),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "chk_runs_period_order",
            "(reporting_period_start IS NULL AND reporting_period_end IS NULL) OR "
            "(reporting_period_start IS NOT NULL AND reporting_period_end IS NOT NULL AND reporting_period_start <= reporting_period_end)",
        )

    # 2. Extend uploaded_file_metadata with S3 storage columns and lifecycle constraints
    with op.batch_alter_table("uploaded_file_metadata") as batch_op:
        batch_op.add_column(
            sa.Column("backend", sa.String(32), server_default="s3", nullable=False)
        )
        batch_op.add_column(
            sa.Column("object_key", sa.String(512), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("lifecycle_state", sa.String(32), server_default="active", nullable=False)
        )
        batch_op.add_column(sa.Column("etag", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("version_id", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("encryption_algorithm", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("retention_eligible_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("legal_hold", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("tombstone", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.create_check_constraint(
            "chk_uploaded_files_lifecycle_allowed",
            "lifecycle_state IN ('staged', 'active', 'tombstoned', 'purged')",
        )
        batch_op.create_check_constraint(
            "chk_uploaded_files_backend_allowed",
            "backend IN ('s3', 'local')",
        )
        batch_op.create_check_constraint(
            "chk_uploaded_files_tombstone_consistency",
            "(tombstone = false AND lifecycle_state != 'tombstoned') OR (tombstone = true AND lifecycle_state IN ('tombstoned', 'purged'))",
        )

    # 3. Extend artifact_metadata with S3 storage columns and lifecycle constraints
    with op.batch_alter_table("artifact_metadata") as batch_op:
        batch_op.add_column(
            sa.Column("backend", sa.String(32), server_default="s3", nullable=False)
        )
        batch_op.add_column(
            sa.Column("object_key", sa.String(512), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("lifecycle_state", sa.String(32), server_default="active", nullable=False)
        )
        batch_op.add_column(sa.Column("etag", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("version_id", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("encryption_algorithm", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("retention_eligible_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("legal_hold", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("tombstone", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.drop_constraint("chk_artifacts_type_allowed", type_="check")
        batch_op.create_check_constraint(
            "chk_artifacts_type_allowed",
            "artifact_type IN ('tally_xml', 'report_json', 'certificate_json', 'recovery_json')",
        )
        batch_op.create_check_constraint(
            "chk_artifacts_lifecycle_allowed",
            "lifecycle_state IN ('staged', 'active', 'tombstoned', 'purged')",
        )
        batch_op.create_check_constraint(
            "chk_artifacts_backend_allowed",
            "backend IN ('s3', 'local')",
        )
        batch_op.create_check_constraint(
            "chk_artifacts_tombstone_consistency",
            "(tombstone = false AND lifecycle_state != 'tombstoned') OR (tombstone = true AND lifecycle_state IN ('tombstoned', 'purged'))",
        )

    # 4. Update audit_events constraints to allow run deletion, purging, and legal hold events
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("chk_audit_events_type_allowed", type_="check")
        batch_op.create_check_constraint(
            "chk_audit_events_type_allowed",
            "event_type IN ("
            "'run.initiated', 'run.completed', 'run.failed', 'certificate.issued', "
            "'membership.assigned', 'organisation.deactivated', "
            "'organisation.created', 'organisation.switched', 'invitation.created', "
            "'invitation.accepted', 'invitation.revoked', 'membership.role_changed', "
            "'membership.suspended', 'membership.reactivated', 'run.deleted', "
            "'run.purged', 'run.legal_hold_placed', 'run.legal_hold_released'"
            ")",
        )

    # 5. Create reconciliation_jobs table
    op.create_table(
        "reconciliation_jobs",
        pk_id_column(),
        sa.Column("public_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(64), server_default="queued", nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("attempt_token", sa.String(64), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.String(255), nullable=True),
        sa.Column("is_cancelled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancelled_by_principal_id",
            sa.BigInteger(),
            sa.ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "run_id"],
            ["reconciliation_runs.organisation_id", "reconciliation_runs.id"],
            ondelete="RESTRICT",
            name="fk_jobs_org_run",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "stage IN ('queued', 'ingesting', 'attributing', 'reconciling', 'investigating', 'persisting', 'completed')",
            name="chk_jobs_stage_allowed",
        ),
        sa.CheckConstraint(
            "("
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND failed_at IS NULL AND attempt_token IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND failed_at IS NULL AND attempt_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at >= started_at AND failed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND failed_at IS NOT NULL AND failed_at >= started_at AND completed_at IS NULL AND error_code IS NOT NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND completed_at IS NULL)"
            ")",
            name="chk_jobs_lifecycle_state_machine",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="chk_jobs_attempt_bounds",
        ),
        sa.CheckConstraint("lease_generation >= 0", name="chk_jobs_generation_bounds"),
    )

    # 6. Create idempotency_records table
    op.create_table(
        "idempotency_records",
        pk_id_column(),
        sa.Column(
            "organisation_id",
            sa.BigInteger(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("reconciliation_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("response_status_code", sa.Integer(), server_default="202", nullable=False),
        sa.Column("response_json", JSONType, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organisation_id", "idempotency_key", name="uq_idempotency_org_key"
        ),
    )

    # 7. PostgreSQL-Specific: RLS and SECURITY DEFINER functions.
    # Roles are provisioned by the deployment/DBA layer (scripts/provision_db_roles.sql),
    # never by application migrations.
    if is_postgres:
        op.execute(
            """
            GRANT USAGE ON SCHEMA public TO untangle_worker;
            REVOKE CREATE ON SCHEMA public FROM untangle_worker;
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM untangle_worker;
            """
        )

        # Enable & force RLS on new tenant tables
        for table in ("reconciliation_jobs", "idempotency_records"):
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
            if table == "reconciliation_jobs":
                # SECURITY DEFINER job functions run as a non-login,
                # non-BYPASSRLS owner and claim/transition jobs across tenants.
                # The owner has no function EXECUTE grants; worker access is
                # exposed only through the narrowly granted functions below.
                op.execute(
                    """
                    CREATE POLICY job_function_owner_select_policy ON reconciliation_jobs
                        FOR SELECT TO untangle_fn_owner USING (true);
                    CREATE POLICY job_function_owner_update_policy ON reconciliation_jobs
                        FOR UPDATE TO untangle_fn_owner
                        USING (true) WITH CHECK (true);
                    """
                )
            op.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO untangle_app;"
            )

        # -------------------------------------------------------------------
        # SECURITY DEFINER Functions owned by untangle_fn_owner
        # -------------------------------------------------------------------

        # 1. fn_job_claim_next
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_claim_next(
                p_worker_id TEXT,
                p_lease_seconds INT,
                p_attempt_token TEXT
            )
            RETURNS TABLE(
                job_id BIGINT,
                public_id VARCHAR(64),
                organisation_id BIGINT,
                run_id BIGINT,
                created_by_principal_id BIGINT,
                attempt_token VARCHAR(64),
                lease_generation INT,
                attempt_count INT
            )
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            BEGIN
                RETURN QUERY
                WITH eligible_job AS (
                    SELECT j.id
                    FROM public.reconciliation_jobs j
                    WHERE (j.status = 'queued' OR (j.status = 'running' AND j.lease_expires_at < clock_timestamp()))
                      AND j.attempt_count < j.max_attempts
                      AND j.is_cancelled = false
                    ORDER BY j.scheduled_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE public.reconciliation_jobs rj
                SET status = 'running',
                    stage = 'ingesting',
                    worker_id = p_worker_id,
                    attempt_token = p_attempt_token,
                    lease_generation = rj.lease_generation + 1,
                    attempt_count = rj.attempt_count + 1,
                    started_at = COALESCE(rj.started_at, clock_timestamp()),
                    last_heartbeat_at = clock_timestamp(),
                    lease_expires_at = clock_timestamp() + (p_lease_seconds || ' seconds')::interval,
                    updated_at = clock_timestamp()
                FROM eligible_job
                WHERE rj.id = eligible_job.id
                RETURNING rj.id, rj.public_id, rj.organisation_id, rj.run_id, rj.created_by_principal_id,
                          rj.attempt_token, rj.lease_generation, rj.attempt_count;
            END;
            $$;
            ALTER FUNCTION public.fn_job_claim_next(TEXT, INT, TEXT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_claim_next(TEXT, INT, TEXT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_claim_next(TEXT, INT, TEXT) TO untangle_worker;
            """
        )

        # 2. fn_job_heartbeat
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_heartbeat(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT,
                p_lease_seconds INT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.reconciliation_jobs
                SET last_heartbeat_at = clock_timestamp(),
                    lease_expires_at = clock_timestamp() + (p_lease_seconds || ' seconds')::interval,
                    updated_at = clock_timestamp()
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_job_heartbeat(BIGINT, TEXT, INT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_heartbeat(BIGINT, TEXT, INT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_heartbeat(BIGINT, TEXT, INT, INT) TO untangle_worker;
            """
        )

        # 3. fn_job_check_cancellation
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_check_cancellation(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_cancelled BOOLEAN;
            BEGIN
                SELECT is_cancelled INTO v_cancelled
                FROM public.reconciliation_jobs
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                RETURN COALESCE(v_cancelled, false);
            END;
            $$;
            ALTER FUNCTION public.fn_job_check_cancellation(BIGINT, TEXT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_check_cancellation(BIGINT, TEXT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_check_cancellation(BIGINT, TEXT, INT) TO untangle_worker;
            """
        )

        # 4. fn_job_transition_stage
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_transition_stage(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT,
                p_stage TEXT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.reconciliation_jobs
                SET stage = p_stage,
                    updated_at = clock_timestamp()
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_job_transition_stage(BIGINT, TEXT, INT, TEXT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_transition_stage(BIGINT, TEXT, INT, TEXT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_transition_stage(BIGINT, TEXT, INT, TEXT) TO untangle_worker;
            """
        )

        # 5. fn_job_fail
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_fail(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT,
                p_error_code TEXT,
                p_error_summary TEXT,
                p_retryable BOOLEAN DEFAULT false
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.reconciliation_jobs
                SET status = CASE WHEN p_retryable AND attempt_count < max_attempts THEN 'queued' ELSE 'failed' END,
                    failed_at = CASE WHEN p_retryable AND attempt_count < max_attempts THEN NULL ELSE clock_timestamp() END,
                    error_code = p_error_code,
                    error_summary = p_error_summary,
                    attempt_token = CASE WHEN p_retryable AND attempt_count < max_attempts THEN NULL ELSE attempt_token END,
                    worker_id = CASE WHEN p_retryable AND attempt_count < max_attempts THEN NULL ELSE worker_id END,
                    lease_expires_at = CASE WHEN p_retryable AND attempt_count < max_attempts THEN NULL ELSE lease_expires_at END,
                    started_at = CASE WHEN p_retryable AND attempt_count < max_attempts THEN NULL ELSE started_at END,
                    stage = CASE WHEN p_retryable AND attempt_count < max_attempts THEN 'queued' ELSE 'completed' END,
                    updated_at = clock_timestamp()
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_job_fail(BIGINT, TEXT, INT, TEXT, TEXT, BOOLEAN) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_fail(BIGINT, TEXT, INT, TEXT, TEXT, BOOLEAN) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_fail(BIGINT, TEXT, INT, TEXT, TEXT, BOOLEAN) TO untangle_worker;
            """
        )

        # 6. fn_job_cancel_ack
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_cancel_ack(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.reconciliation_jobs
                SET status = 'cancelled',
                    cancelled_at = COALESCE(cancelled_at, clock_timestamp()),
                    updated_at = clock_timestamp()
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_job_cancel_ack(BIGINT, TEXT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_cancel_ack(BIGINT, TEXT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_cancel_ack(BIGINT, TEXT, INT) TO untangle_worker;
            """
        )

        # 7. fn_job_revalidate_creator
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_revalidate_creator(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_org_id BIGINT;
                v_creator_id BIGINT;
                v_is_valid BOOLEAN := false;
            BEGIN
                SELECT organisation_id, created_by_principal_id
                INTO v_org_id, v_creator_id
                FROM public.reconciliation_jobs
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';

                IF v_org_id IS NULL THEN
                    RETURN false;
                END IF;

                -- Verify active membership with prepared capability (owner, admin, operator)
                SELECT EXISTS(
                    SELECT 1
                    FROM public.organisation_memberships m
                    JOIN public.roles r ON m.role_id = r.id
                    WHERE m.organisation_id = v_org_id
                      AND m.principal_id = v_creator_id
                      AND m.status = 'active'
                      AND r.code IN ('owner', 'admin', 'operator')
                ) INTO v_is_valid;

                RETURN v_is_valid;
            END;
            $$;
            ALTER FUNCTION public.fn_job_revalidate_creator(BIGINT, TEXT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_revalidate_creator(BIGINT, TEXT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_revalidate_creator(BIGINT, TEXT, INT) TO untangle_worker;
            """
        )

        # 8. fn_job_complete
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.fn_job_complete(
                p_job_id BIGINT,
                p_attempt_token TEXT,
                p_lease_generation INT
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                v_rows INT;
            BEGIN
                UPDATE public.reconciliation_jobs
                SET status = 'completed',
                    stage = 'completed',
                    completed_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                WHERE id = p_job_id
                  AND attempt_token = p_attempt_token
                  AND lease_generation = p_lease_generation
                  AND status = 'running';
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                RETURN v_rows > 0;
            END;
            $$;
            ALTER FUNCTION public.fn_job_complete(BIGINT, TEXT, INT) OWNER TO untangle_fn_owner;
            REVOKE ALL ON FUNCTION public.fn_job_complete(BIGINT, TEXT, INT) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.fn_job_complete(BIGINT, TEXT, INT) TO untangle_worker;
            GRANT EXECUTE ON FUNCTION public.fn_job_complete(BIGINT, TEXT, INT) TO untangle_app;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_complete(BIGINT, TEXT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_revalidate_creator(BIGINT, TEXT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_cancel_ack(BIGINT, TEXT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_fail(BIGINT, TEXT, INT, TEXT, TEXT, BOOLEAN);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_transition_stage(BIGINT, TEXT, INT, TEXT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_check_cancellation(BIGINT, TEXT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_heartbeat(BIGINT, TEXT, INT, INT);")
        op.execute("DROP FUNCTION IF EXISTS public.fn_job_claim_next(TEXT, INT, TEXT);")

        for table in ("idempotency_records", "reconciliation_jobs"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS job_function_owner_select_policy ON reconciliation_jobs;")
        op.execute("DROP POLICY IF EXISTS job_function_owner_update_policy ON reconciliation_jobs;")

    op.drop_table("idempotency_records")
    op.drop_table("reconciliation_jobs")

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("chk_audit_events_type_allowed", type_="check")
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

    with op.batch_alter_table("artifact_metadata") as batch_op:
        batch_op.drop_constraint("chk_artifacts_tombstone_consistency", type_="check")
        batch_op.drop_constraint("chk_artifacts_backend_allowed", type_="check")
        batch_op.drop_constraint("chk_artifacts_lifecycle_allowed", type_="check")
        batch_op.drop_constraint("chk_artifacts_type_allowed", type_="check")
        batch_op.create_check_constraint(
            "chk_artifacts_type_allowed",
            "artifact_type IN ('tally_xml', 'report_json', 'certificate_json')",
        )
        batch_op.drop_column("tombstone")
        batch_op.drop_column("legal_hold")
        batch_op.drop_column("retention_eligible_at")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("promoted_at")
        batch_op.drop_column("encryption_algorithm")
        batch_op.drop_column("version_id")
        batch_op.drop_column("etag")
        batch_op.drop_column("lifecycle_state")
        batch_op.drop_column("object_key")
        batch_op.drop_column("backend")

    with op.batch_alter_table("uploaded_file_metadata") as batch_op:
        batch_op.drop_constraint("chk_uploaded_files_tombstone_consistency", type_="check")
        batch_op.drop_constraint("chk_uploaded_files_backend_allowed", type_="check")
        batch_op.drop_constraint("chk_uploaded_files_lifecycle_allowed", type_="check")
        batch_op.drop_column("tombstone")
        batch_op.drop_column("legal_hold")
        batch_op.drop_column("retention_eligible_at")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("promoted_at")
        batch_op.drop_column("encryption_algorithm")
        batch_op.drop_column("version_id")
        batch_op.drop_column("etag")
        batch_op.drop_column("lifecycle_state")
        batch_op.drop_column("object_key")
        batch_op.drop_column("backend")

    with op.batch_alter_table("reconciliation_runs") as batch_op:
        batch_op.drop_constraint("chk_runs_period_order", type_="check")
        batch_op.drop_column("parent_run_id")
        batch_op.drop_column("bank_adapter_version")
        batch_op.drop_column("bank_adapter_id")
        batch_op.drop_column("rule_pack_version")
        batch_op.drop_column("rule_pack_id")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("engine_version")
        batch_op.drop_column("legal_hold")
        batch_op.drop_column("reporting_period_end")
        batch_op.drop_column("reporting_period_start")

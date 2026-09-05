-- =============================================================================
-- Untangle Database Role Provisioning Script (PostgreSQL 16+)
--
-- This script must be executed by a PostgreSQL superuser / database administrator
-- during environment setup. Application startup and migrations DO NOT provision roles.
--
-- Roles:
--   1. untangle_migrator: Owns schema, executes DDL migrations and trigger creation.
--   2. untangle_app: Unprivileged runtime application user. Subject to RLS.
--      Cannot ALTER tables, cannot DISABLE TRIGGERS, cannot TRUNCATE records.
-- =============================================================================

-- Credentials and roles must be created by the deployment control plane or DBA.
-- This repository intentionally does not contain default database passwords.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_migrator') THEN
        RAISE EXCEPTION 'Required role untangle_migrator has not been provisioned';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_app') THEN
        RAISE EXCEPTION 'Required role untangle_app has not been provisioned';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_fn_owner') THEN
        RAISE EXCEPTION 'Required role untangle_fn_owner has not been provisioned';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_auth') THEN
        RAISE EXCEPTION 'Required role untangle_auth has not been provisioned';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_maintenance') THEN
        RAISE EXCEPTION 'Required role untangle_maintenance has not been provisioned';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_worker') THEN
        RAISE EXCEPTION 'Required role untangle_worker has not been provisioned';
    END IF;
END;
$$;

-- 2. Schema Privileges and Ownership
-- CRITICAL: Grant function execution owner role to migrator so it can transfer ownership during migrations
GRANT untangle_fn_owner TO untangle_migrator;

ALTER SCHEMA public OWNER TO untangle_migrator;
GRANT USAGE ON SCHEMA public TO untangle_app, untangle_auth, untangle_maintenance, untangle_worker;

-- Prevent arbitrary table or function creation by unprivileged roles
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM untangle_app, untangle_auth, untangle_maintenance, untangle_worker;

-- 4. Explicit Per-Table Grants for Runtime Application Role
-- Control-plane access is deliberately not granted to the data-plane role.
-- Phase 2 must provide a separately authorized bootstrap path after authentication.

-- On a fresh database these tables do not exist until the initial Alembic migration runs,
-- which would abort this script with missing-relation errors. Apply the grants conditionally
-- so provisioning is safe to run BEFORE or AFTER the first migration; the initial migration
-- also issues these grants after creating the tables (authoritative for fresh installs).
-- Presence of reconciliation_runs is used as the proxy for "schema has been migrated".
DO $$
BEGIN
    IF to_regclass('public.reconciliation_runs') IS NOT NULL THEN
        -- Tenant Data-Plane: Standard CRUD scoped by Row-Level Security
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON reconciliation_runs TO untangle_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON uploaded_file_metadata TO untangle_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON investigations TO untangle_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON artifact_metadata TO untangle_app';
        -- Immutable Ledgers: SELECT and INSERT only. UPDATE and DELETE are not granted (and trigger-blocked)
        EXECUTE 'GRANT SELECT, INSERT ON reconciliation_results TO untangle_app';
        EXECUTE 'GRANT SELECT, INSERT ON certificates TO untangle_app';
        EXECUTE 'GRANT SELECT, INSERT ON audit_events TO untangle_app';
    END IF;
    IF to_regclass('public.reconciliation_jobs') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON reconciliation_jobs TO untangle_app';
    END IF;
    IF to_regclass('public.idempotency_records') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_records TO untangle_app';
    END IF;
END;
$$;

-- Schema verification reads only Alembic's bookkeeping table.  It may not exist yet when
-- this provisioning script runs before the first migration, so apply the grant conditionally;
-- the initial migration repeats it after creating the table.
DO $$
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT ON TABLE public.alembic_version TO untangle_app';
    END IF;
END;
$$;

-- Sequence Privileges (for autoincrementing IDs)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO untangle_app;

-- Ensure future sequences created by migrator grant usage to untangle_app
ALTER DEFAULT PRIVILEGES FOR ROLE untangle_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO untangle_app;

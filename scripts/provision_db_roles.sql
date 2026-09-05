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
END;
$$;

-- 2. Create Runtime Application Role (Unprivileged, NO SUPERUSER, NO BYPASSRLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_app') THEN
        RAISE EXCEPTION 'Required role untangle_app has not been provisioned';
    END IF;
END;
$$;

-- 3. Schema Privileges. The DBA must set database ownership and CONNECT
-- privileges explicitly for the target database before running this script.
ALTER SCHEMA public OWNER TO untangle_migrator;
GRANT USAGE ON SCHEMA public TO untangle_app;

-- 4. Explicit Per-Table Grants for Runtime Application Role
-- Control-plane access is deliberately not granted to the data-plane role.
-- Phase 2 must provide a separately authorized bootstrap path after authentication.

-- Tenant Data-Plane: Standard CRUD scoped by Row-Level Security
GRANT SELECT, INSERT, UPDATE, DELETE ON reconciliation_runs TO untangle_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON uploaded_file_metadata TO untangle_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON investigations TO untangle_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON artifact_metadata TO untangle_app;

-- Immutable Ledgers: SELECT and INSERT only. UPDATE and DELETE are not granted (and trigger-blocked)
GRANT SELECT, INSERT ON reconciliation_results TO untangle_app;
GRANT SELECT, INSERT ON certificates TO untangle_app;
GRANT SELECT, INSERT ON audit_events TO untangle_app;

-- Sequence Privileges (for autoincrementing IDs)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO untangle_app;

-- Ensure future sequences created by migrator grant usage to untangle_app
ALTER DEFAULT PRIVILEGES FOR ROLE untangle_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO untangle_app;

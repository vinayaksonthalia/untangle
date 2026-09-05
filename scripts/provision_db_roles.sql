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

-- 1. Create Migration / Schema Owner Role
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_migrator') THEN
        CREATE ROLE untangle_migrator WITH LOGIN PASSWORD 'change_this_migrator_password';
    END IF;
END
$$;

-- 2. Create Runtime Application Role (Unprivileged, NO SUPERUSER, NO BYPASSRLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'untangle_app') THEN
        CREATE ROLE untangle_app WITH LOGIN PASSWORD 'change_this_runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- 3. Database Ownership & Schema Privileges
ALTER DATABASE untangle OWNER TO untangle_migrator;
GRANT CONNECT ON DATABASE untangle TO untangle_app;

-- Run subsequent commands connected to database 'untangle':
\c untangle

ALTER SCHEMA public OWNER TO untangle_migrator;
GRANT USAGE ON SCHEMA public TO untangle_app;

-- 4. Explicit Per-Table Grants for Runtime Application Role
-- Control-Plane: Read-only for identity lookup during tenant bootstrap
GRANT SELECT ON organisations TO untangle_app;
GRANT SELECT ON principals TO untangle_app;
GRANT SELECT ON roles TO untangle_app;
GRANT SELECT ON organisation_memberships TO untangle_app;

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

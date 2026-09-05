"""Live-PostgreSQL regression for the fresh-database provisioning lifecycle (Qodo #72).

Reproduces the original defect and proves the fix end to end against a real PostgreSQL
server: the provisioning script must succeed BEFORE the tables exist (the old unconditional
grants aborted here), and after Alembic runs the runtime role must hold exactly the intended
table privileges. Re-running the script post-migration must also succeed (idempotent).

Gated on POSTGRES_PROVISIONING_TEST_URL — a superuser SQLAlchemy URL (e.g.
``postgresql+psycopg://postgres:postgres@localhost:5432/postgres``) with permission to create
roles and databases. Skipped when unset, so it does not affect the default SQLite test run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

_URL = os.environ.get("POSTGRES_PROVISIONING_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not _URL,
    reason="set POSTGRES_PROVISIONING_TEST_URL (a superuser URL) to run provisioning integration",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISION_SQL = REPO_ROOT / "scripts/provision_db_roles.sql"
MIGRATOR = "untangle_migrator"
APP = "untangle_app"
TEST_DB = "untangle_provtest"
MIGRATOR_PW = "provtest_migrator_pw"  # noqa: S105 - throwaway local test role, not a real secret

CRUD = {"SELECT", "INSERT", "UPDATE", "DELETE"}
APPEND_ONLY = {"SELECT", "INSERT"}


def _split_sql(script: str) -> list[str]:
    """Split a SQL script into statements, honouring ``$$``-quoted DO blocks.

    Top-level ``--`` line comments are skipped so a semicolon inside a comment cannot be
    mistaken for a statement terminator; comments inside a ``$$`` block are left intact.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar = False
    i = 0
    while i < len(script):
        if not in_dollar and script[i : i + 2] == "--":
            newline = script.find("\n", i)
            i = len(script) if newline == -1 else newline
            continue
        if script[i : i + 2] == "$$":
            in_dollar = not in_dollar
            buffer.append("$$")
            i += 2
            continue
        char = script[i]
        if char == ";" and not in_dollar:
            stmt = "".join(buffer).strip()
            if stmt:
                statements.append(stmt)
            buffer = []
        else:
            buffer.append(char)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _run_script(conn, path: Path) -> None:
    for statement in _split_sql(path.read_text()):
        conn.exec_driver_sql(statement)


def test_fresh_provisioning_then_migration_grants_exact_privileges() -> None:
    super_engine = create_engine(_URL, isolation_level="AUTOCOMMIT")
    test_db_url = make_url(_URL).set(database=TEST_DB)
    db_super_engine = create_engine(test_db_url, isolation_level="AUTOCOMMIT")
    try:
        # Provision throwaway roles and a fresh, empty database owned by the migrator.
        with super_engine.connect() as conn:
            conn.exec_driver_sql(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{MIGRATOR}') "
                f"THEN CREATE ROLE {MIGRATOR} LOGIN PASSWORD '{MIGRATOR_PW}'; END IF; END $$;"
            )
            conn.exec_driver_sql(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{APP}') "
                f"THEN CREATE ROLE {APP} NOSUPERUSER NOBYPASSRLS; END IF; END $$;"
            )
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.exec_driver_sql(f"CREATE DATABASE {TEST_DB} OWNER {MIGRATOR}")

        # 1) FRESH provisioning must succeed on a database with no application tables yet.
        #    Under the previous unconditional grants this aborted with missing-relation errors.
        with db_super_engine.connect() as conn:
            conn.exec_driver_sql(f"GRANT CONNECT ON DATABASE {TEST_DB} TO {APP}")
            _run_script(conn, PROVISION_SQL)

            # Sanity: the tenant tables genuinely do not exist yet.
            exists = conn.exec_driver_sql(
                "SELECT to_regclass('public.reconciliation_runs')"
            ).scalar()
            assert exists is None

        # 2) Apply the initial migration as the migrator; it creates the tables and issues the
        #    authoritative grants.
        from persistence.migrate import upgrade_head

        migrator_url = make_url(_URL).set(
            username=MIGRATOR, password=MIGRATOR_PW, database=TEST_DB
        )
        upgrade_head(migrator_url.render_as_string(hide_password=False))

        # 3) The runtime role now holds exactly the intended privileges.
        with db_super_engine.connect() as conn:
            rows = conn.exec_driver_sql(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                f"WHERE grantee = '{APP}' AND table_schema = 'public'"
            ).fetchall()
        grants: dict[str, set[str]] = {}
        for table_name, privilege in rows:
            grants.setdefault(table_name, set()).add(privilege)

        for table in (
            "reconciliation_runs",
            "uploaded_file_metadata",
            "investigations",
            "artifact_metadata",
        ):
            assert grants.get(table) == CRUD, (table, grants.get(table))
        for table in ("reconciliation_results", "certificates", "audit_events"):
            assert grants.get(table) == APPEND_ONLY, (table, grants.get(table))
            # Immutable ledgers must never receive UPDATE/DELETE.
            assert "UPDATE" not in grants.get(table, set())
            assert "DELETE" not in grants.get(table, set())
        assert grants.get("alembic_version") == {"SELECT"}

        # 4) Re-running provisioning after migration is idempotent and still succeeds.
        with db_super_engine.connect() as conn:
            _run_script(conn, PROVISION_SQL)
    finally:
        db_super_engine.dispose()
        with super_engine.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        super_engine.dispose()

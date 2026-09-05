"""Regression coverage for fail-closed migration operations and provenance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from persistence.migrate import get_alembic_config, get_migration_provenance


def test_migration_apis_resolve_from_a_foreign_working_directory(tmp_path: Path) -> None:
    """Regression: run provenance and head discovery in a SUBPROCESS whose working directory is
    a non-repository directory. Under the previous relative script_location this failed with
    "Path doesn't exist: migrations" because Alembic resolved script_location against the CWD;
    the absolute script_location fixes it. Repository-root coverage is retained by
    test_migration_provenance_is_repository_derived below."""
    repo_root = Path(__file__).resolve().parents[2]
    program = (
        "from persistence.migrate import get_migration_provenance, get_head_revision\n"
        "p = get_migration_provenance()\n"
        "assert p['revision'] == '0003_reconciliation_jobs_and_storage', p\n"
        "assert get_head_revision() == '0003_reconciliation_jobs_and_storage'\n"
        "print('PROVENANCE_OK')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root), env.get("PYTHONPATH", "")])
    env.pop("DATABASE_URL", None)
    env.pop("MIGRATION_DATABASE_URL", None)

    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,  # deliberately outside the repository
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PROVENANCE_OK" in result.stdout


def test_fresh_provisioning_defers_data_table_grants_to_migration() -> None:
    """Regression: on a fresh database the tenant-table grants must not run before Alembic
    creates the tables (that aborts setup with missing-relation errors). The provisioning script
    guards those grants behind a to_regclass() existence check, and the initial migration issues
    the authoritative grants after creating the tables."""
    root = Path(__file__).resolve().parents[2]
    provisioning = (root / "scripts/provision_db_roles.sql").read_text()
    migration = (root / "migrations/versions/0001_initial_tenant_schema.py").read_text()

    data_tables = [
        "reconciliation_runs",
        "uploaded_file_metadata",
        "investigations",
        "artifact_metadata",
        "reconciliation_results",
        "certificates",
        "audit_events",
    ]
    guard = "IF to_regclass('public.reconciliation_runs') IS NOT NULL THEN"
    assert guard in provisioning
    before_guard, guarded_region = provisioning.split(guard, 1)
    for table in data_tables:
        grant_fragment = f"ON {table} TO untangle_app"
        # Every tenant-table grant lives only inside the existence-guarded block...
        assert grant_fragment in guarded_region
        # ...and never runs unconditionally before the guard on a fresh database.
        assert grant_fragment not in before_guard

    # The migration issues the authoritative grants after the tables are created.
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON {_crud_table} TO untangle_app" in migration
    assert "GRANT SELECT, INSERT ON {_append_only_table} TO untangle_app" in migration


def test_migration_provenance_is_repository_derived() -> None:
    provenance = get_migration_provenance()

    assert provenance == {
        "revision": "0003_reconciliation_jobs_and_storage",
        "down_revision": "0002_auth_federation_sessions",
        "source_file": "migrations/versions/0003_reconciliation_jobs_and_storage.py",
        "summary": "Durable reconciliation jobs, idempotency records, S3 storage metadata, and worker functions.",
        "created_by": "vinayaksonthalia",
        "created_at": "2026-09-05T19:45:00Z",
        "source": "docs/PRODUCT_COMPLETION_ROADMAP.md#phase-3--saved-runs-and-multi-month-workspace",
    }


def test_explicit_migration_config_requires_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="Neither MIGRATION_DATABASE_URL nor DATABASE_URL"):
        get_alembic_config()


def test_alembic_command_does_not_fall_back_to_memory_database() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    environment.pop("MIGRATION_DATABASE_URL", None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Neither MIGRATION_DATABASE_URL nor DATABASE_URL" in result.stderr


def test_runtime_role_has_read_only_migration_revision_access() -> None:
    provisioning = (
        Path(__file__).resolve().parents[2] / "scripts/provision_db_roles.sql"
    ).read_text()
    migration = (
        Path(__file__).resolve().parents[2] / "migrations/versions/0001_initial_tenant_schema.py"
    ).read_text()

    assert "GRANT SELECT ON TABLE public.alembic_version TO untangle_app" in provisioning
    assert "GRANT SELECT ON TABLE alembic_version TO untangle_app" in migration

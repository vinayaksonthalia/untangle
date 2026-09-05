"""Regression coverage for fail-closed migration operations and provenance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from persistence.migrate import (
    get_alembic_config,
    get_head_revision,
    get_migration_provenance,
)


def test_migration_apis_resolve_from_any_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: get_alembic_config pins an absolute script_location, so provenance and head
    discovery work even when the process working directory is not the repository root. Under the
    previous relative script_location, ScriptDirectory.from_config resolved against the CWD and
    failed outside the repo root."""
    monkeypatch.chdir(tmp_path)
    provenance = get_migration_provenance()
    assert provenance["revision"] == "0001_initial_tenant_schema"
    assert get_head_revision() == "0001_initial_tenant_schema"


def test_fresh_provisioning_defers_data_table_grants_to_migration() -> None:
    """Regression: on a fresh database the tenant-table grants must not run before Alembic
    creates the tables (that aborts setup with missing-relation errors). The provisioning script
    guards those grants behind a to_regclass() existence check, and the initial migration issues
    the authoritative grants after creating the tables."""
    root = Path(__file__).resolve().parents[2]
    provisioning = (root / "scripts/provision_db_roles.sql").read_text()
    migration = (
        root / "migrations/versions/0001_initial_tenant_schema.py"
    ).read_text()

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
        "revision": "0001_initial_tenant_schema",
        "down_revision": None,
        "source_file": "migrations/versions/0001_initial_tenant_schema.py",
        "summary": "Initial multi-tenant schema with composite constraints, RLS, and immutability triggers.",
        "created_by": "vinayaksonthalia",
        "created_at": "2026-09-05T03:44:44Z",
        "source": "docs/PERSISTENCE_AND_TENANT_ISOLATION.md#entity--ownership-model",
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

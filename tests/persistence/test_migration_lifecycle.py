"""Migration lifecycle and schema verification tests."""

from __future__ import annotations

import pytest

from persistence.migrate import (
    SchemaOutOfDateError,
    check_schema_current,
    downgrade,
    get_current_revision,
    get_head_revision,
    upgrade_head,
    verify_schema_current,
)


def test_migration_head_exists() -> None:
    head = get_head_revision()
    assert head == "0001_initial_tenant_schema"


def test_schema_verification_detects_unmigrated_db(tmp_path) -> None:
    # Fresh empty SQLite database has no alembic_version table
    empty_url = f"sqlite:///{tmp_path}/empty.db"
    assert get_current_revision(empty_url) is None
    assert check_schema_current(empty_url) is False

    with pytest.raises(SchemaOutOfDateError) as exc_info:
        verify_schema_current(empty_url)
    assert "Database schema is out of date" in str(exc_info.value)


def test_migration_upgrade_and_downgrade_cycle(tmp_path) -> None:
    db_file = tmp_path / "cycle.db"
    test_url = f"sqlite:///{db_file}"

    # 1. Upgrade from clean state to head
    upgrade_head(test_url)
    assert get_current_revision(test_url) == "0001_initial_tenant_schema"
    assert check_schema_current(test_url) is True
    verify_schema_current(test_url)

    # 2. Downgrade by one revision (to base)
    downgrade("base", test_url)
    assert get_current_revision(test_url) is None
    assert check_schema_current(test_url) is False

    # 3. Re-upgrade to head
    upgrade_head(test_url)
    assert get_current_revision(test_url) == "0001_initial_tenant_schema"
    assert check_schema_current(test_url) is True

"""Integration tests for database backup and restoration verification script."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.verify_restore import (
    run_migrations,
    verify_database_schema,
)


def test_verify_restore_script_fresh_db() -> None:
    """Test that verify_restore.py succeeds on a clean database migration."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_verify.db"
        db_url = f"sqlite:///{db_path}"

        run_migrations(db_url)
        assert verify_database_schema(db_url) is True


def test_verify_restore_script_cli_invocation() -> None:
    """Test that verify_restore.py can be invoked via CLI subprocess successfully."""
    cmd = [sys.executable, "scripts/verify_restore.py"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "[SUCCESS] Restoration integrity verification passed completely." in res.stdout


def test_verify_restore_detects_unmigrated_db() -> None:
    """Test that verify_database_schema detects an unmigrated empty database."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "empty.db"
        db_url = f"sqlite:///{db_path}"
        # Do not run migrations
        assert verify_database_schema(db_url) is False

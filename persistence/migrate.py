"""Alembic migration runner and startup verification commands.

CLI commands:
    python -m persistence.migrate upgrade head
    python -m persistence.migrate downgrade -1
    python -m persistence.migrate current
    python -m persistence.migrate check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from persistence.config import get_migration_database_url


class SchemaOutOfDateError(RuntimeError):
    """Raised when application startup detects an unmigrated database."""


def get_migration_provenance() -> dict[str, object]:
    """Return truthful, machine-readable metadata for the repository migration head.

    Creator and timestamp values are embedded in the migration from the introducing Git commit.
    """
    repo_root = Path(__file__).resolve().parents[1]
    cfg = get_alembic_config(url=None, require_url=False)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("No head migration found in migrations directory")
    revision = script.get_revision(head)
    if revision is None:  # pragma: no cover - ScriptDirectory guarantees this for a head
        raise RuntimeError(f"Migration head {head!r} is missing")
    down_revision: object = revision.down_revision
    if isinstance(down_revision, tuple):
        down_revision = list(down_revision)
    embedded = getattr(revision.module, "MIGRATION_PROVENANCE", None)
    if not isinstance(embedded, dict):
        raise RuntimeError(f"Migration {head!r} is missing machine-readable provenance")
    return {
        "revision": revision.revision,
        "down_revision": down_revision,
        "source_file": str(Path(revision.path).resolve().relative_to(repo_root)),
        "summary": revision.doc,
        **embedded,
    }


def get_alembic_config(url: str | None = None, require_url: bool = True) -> Config:
    """Create an Alembic Config object pointing to the repository migration scripts."""
    repo_root = Path(__file__).resolve().parents[1]
    ini_path = repo_root / "alembic.ini"
    cfg = Config(str(ini_path))
    # Resolve the migration scripts by absolute path. Alembic otherwise interprets the
    # ini's relative script_location against the caller's working directory, so the
    # documented APIs (provenance, head, upgrade) would fail when run outside the repo root.
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    elif require_url:
        db_url = get_migration_database_url()
        cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def upgrade_head(url: str | None = None) -> None:
    """Upgrade database schema to the latest migration revision."""
    cfg = get_alembic_config(url)
    command.upgrade(cfg, "head")


def downgrade(revision: str = "-1", url: str | None = None) -> None:
    """Downgrade database schema by the specified revision."""
    cfg = get_alembic_config(url)
    command.downgrade(cfg, revision)


def get_current_revision(url: str | None = None) -> str | None:
    """Return the current active migration revision on the database, or None if unmigrated."""
    from persistence.config import create_db_engine

    db_url = url or get_migration_database_url()
    engine = create_db_engine(db_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def get_head_revision(url: str | None = None) -> str:
    """Return the expected head revision defined in migration scripts."""
    cfg = get_alembic_config(url, require_url=False)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("No head migration found in migrations directory")
    return head


def check_schema_current(url: str | None = None) -> bool:
    """Return True if current database schema matches the expected head revision."""
    current = get_current_revision(url)
    head = get_head_revision(url)
    return current == head


def verify_schema_current(url: str | None = None) -> None:
    """Verify that the database schema is at head; raise SchemaOutOfDateError if not."""
    current = get_current_revision(url)
    head = get_head_revision(url)
    if current != head:
        raise SchemaOutOfDateError(
            f"Database schema is out of date (current={current!r}, head={head!r}). "
            "Run 'python -m persistence.migrate upgrade head' before starting the service."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Untangle persistence migration manager")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    up_parser = subparsers.add_parser("upgrade", help="Upgrade schema")
    up_parser.add_argument(
        "revision", nargs="?", default="head", help="Target revision (default: head)"
    )

    down_parser = subparsers.add_parser("downgrade", help="Downgrade schema")
    down_parser.add_argument(
        "revision", nargs="?", default="-1", help="Target revision (default: -1)"
    )

    subparsers.add_parser("current", help="Show current schema revision")
    subparsers.add_parser("check", help="Check if schema matches head")

    args = parser.parse_args()

    try:
        if args.cmd == "upgrade":
            cfg = get_alembic_config()
            command.upgrade(cfg, args.revision)
            print(f"Upgraded schema to {args.revision}")
        elif args.cmd == "downgrade":
            cfg = get_alembic_config()
            command.downgrade(cfg, args.revision)
            print(f"Downgraded schema to {args.revision}")
        elif args.cmd == "current":
            rev = get_current_revision()
            print(f"Current revision: {rev or 'None (unmigrated)'}")
        elif args.cmd == "check":
            is_current = check_schema_current()
            current = get_current_revision()
            head = get_head_revision()
            print(
                f"Schema status: current={current}, head={head} -> {'OK' if is_current else 'OUT OF DATE'}"
            )
            return 0 if is_current else 1
        return 0
    except Exception as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

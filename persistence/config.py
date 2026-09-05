"""Database engine configuration, connection management, and session factory.

Provides separate configuration for runtime application access vs migration access.
Does not create database roles at runtime; administrative provisioning is separated.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# Runtime database URL (unprivileged role)
ENV_DATABASE_URL = "DATABASE_URL"
# Migration database URL (privileged schema-owner role)
ENV_MIGRATION_DATABASE_URL = "MIGRATION_DATABASE_URL"


def get_database_url() -> str | None:
    """Return the runtime application database URL or None if unconfigured."""
    url = os.environ.get(ENV_DATABASE_URL, "").strip()
    return url if url else None


def get_migration_database_url() -> str:
    """Return the migration database URL, falling back to DATABASE_URL."""
    migration_url = os.environ.get(ENV_MIGRATION_DATABASE_URL, "").strip()
    if migration_url:
        return migration_url
    runtime_url = get_database_url()
    if runtime_url:
        return runtime_url
    raise RuntimeError(
        f"Neither {ENV_MIGRATION_DATABASE_URL} nor {ENV_DATABASE_URL} is configured."
    )


def create_db_engine(url: str, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine configured for PostgreSQL or SQLite.

    For SQLite, automatically enables foreign key enforcement on every connection.
    For PostgreSQL, enables pool pre-ping to detect stale connections.
    """
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
    engine_kwargs.update(kwargs)

    # SQLite specific configuration
    if url.startswith("sqlite"):
        engine_kwargs.pop("pool_pre_ping", None)
        engine = create_engine(url, **engine_kwargs)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        return engine

    # PostgreSQL / other dialect configuration
    return create_engine(url, **engine_kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a thread-safe SQLAlchemy session factory."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

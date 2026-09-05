"""Unit of Work context manager and collision retry support.

Binds PostgreSQL Row-Level Security tenant settings transaction-locally via set_config
and handles public ID collisions cleanly using savepoints.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext


class PublicIdCollisionError(IntegrityError):
    """Raised when public ID generation fails due to persistent collisions."""


class UnitOfWork:
    """Manages session lifecycle and transaction-scoped RLS tenant context."""

    def __init__(self, session_factory: sessionmaker[Session], context: TenantContext) -> None:
        self._session_factory = session_factory
        self.context = context
        self.session: Session | None = None

    def __enter__(self) -> UnitOfWork:
        self.session = self._session_factory()
        try:
            self.session.begin()

            # Bind transaction-local tenant identity for PostgreSQL RLS
            bind = self.session.get_bind()
            if bind.dialect.name == "postgresql":
                self.session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                    {"tid": str(self.context.organisation_id)},
                )
                active_tid = self.session.execute(
                    text("SELECT current_setting('app.current_tenant_id', true)")
                ).scalar()
                if active_tid != str(self.context.organisation_id):
                    raise RuntimeError(
                        f"Failed to set app.current_tenant_id: expected {self.context.organisation_id}, got {active_tid!r}"
                    )
            return self
        except BaseException:
            self.session.rollback()
            self.session.close()
            self.session = None
            raise

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.session is None:
            return
        try:
            if exc_type is not None:
                self.session.rollback()
            else:
                self.session.commit()
        finally:
            self.session.close()
            self.session = None


def insert_with_public_id_retry[T](
    session: Session,
    create_fn: Callable[[], T],
    expected_constraint: str,
    max_retries: int = 3,
) -> T:
    """Insert a record with savepoint-nested retry for public ID collisions.

    Inspects SQLSTATE 23505 and the exact constraint name to ensure unrelated
    foreign key or business constraint failures are never mistakenly retried.
    """
    for attempt in range(max_retries):
        try:
            with session.begin_nested():
                record = create_fn()
                session.add(record)
                session.flush()
            return record
        except IntegrityError as exc:
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
            diag = getattr(orig, "diag", None)
            constraint_name = getattr(diag, "constraint_name", None)

            # Check if this error is specifically the expected unique constraint
            is_expected_collision = False
            if sqlstate == "23505" and constraint_name == expected_constraint:
                is_expected_collision = True
            else:
                # Fallback for SQLite which does not have psycopg diag attributes
                err_str = str(exc).lower()
                if "unique constraint failed" in err_str:
                    if expected_constraint.lower() in err_str:
                        is_expected_collision = True
                    elif "public_id" in expected_constraint.lower() and "public_id" in err_str:
                        is_expected_collision = True

            if is_expected_collision:
                if attempt == max_retries - 1:
                    raise PublicIdCollisionError(
                        f"Failed to insert record after {max_retries} public ID collision retries",
                        orig=orig,
                        params=exc.params,
                        statement=exc.statement,
                    ) from exc
                continue

            # Unrelated integrity error (foreign key, check constraint, etc.) - do not retry!
            raise
    raise RuntimeError("Unreachable: retry loop terminated without result or exception")

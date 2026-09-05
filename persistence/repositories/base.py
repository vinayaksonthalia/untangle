"""Base repository helpers and query scoping utilities.

Every tenant query MUST enforce tenant scoping at the repository level as Layer 1 defence.
"""

from __future__ import annotations

from sqlalchemy import Select, select

from persistence.context import TenantContext


class RepositoryError(Exception):
    """Base exception for persistence repository errors."""


class RecordNotFoundError(RepositoryError):
    """Raised when a requested record does not exist or is not owned by the tenant."""


def scoped_select[T](model: type[T], context: TenantContext) -> Select[tuple[T]]:
    """Build a Select query filtered explicitly to the context's organisation_id.

    If the model supports soft-deletion (has `is_deleted`), also filters out deleted rows.
    """
    stmt = select(model).where(model.organisation_id == context.organisation_id)
    if hasattr(model, "is_deleted"):
        stmt = stmt.where(model.is_deleted.is_(False))
    return stmt

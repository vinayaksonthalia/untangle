"""Immutable TenantContext and Role specifications.

Tenant identity is authoritative internal primary keys, not arbitrary browser strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"


class TenantContextError(ValueError):
    """Raised when an invalid TenantContext is created or accessed."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Authoritative, immutable tenant context passed explicitly down the call graph.

    Contains strictly verified internal identity records and an active role.
    Public identifiers (org_..., usr_...) are transport representations resolved
    at the boundary, not authorization facts stored in this context.
    """

    organisation_id: int
    principal_id: int
    role: Role
    request_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.organisation_id, int) or self.organisation_id <= 0:
            raise TenantContextError(
                f"organisation_id must be a positive integer, got {self.organisation_id!r}"
            )
        if not isinstance(self.principal_id, int) or self.principal_id <= 0:
            raise TenantContextError(
                f"principal_id must be a positive integer, got {self.principal_id!r}"
            )
        if not isinstance(self.role, Role):
            raise TenantContextError(f"role must be an instance of Role enum, got {self.role!r}")
        if not isinstance(self.request_id, str):
            raise TenantContextError(f"request_id must be a string, got {self.request_id!r}")

    def has_role(self, *allowed: Role) -> bool:
        """Check if the context's role is in the allowed roles."""
        return self.role in allowed

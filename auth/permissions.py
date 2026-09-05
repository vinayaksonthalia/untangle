"""Authoritative 5-role capability checker and permission enforcement matrix.

Supported roles:
- owner: Full organization authority (lifecycle, memberships, certification).
- admin: Organizational administration (memberships up to admin, operations).
- operator: Preparer (run execution, file upload, investigation resolution; NO certification).
- reviewer: Approver (review, certificate issuance; NO run execution).
- auditor: Read-only inspection across all runs and certificates.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from persistence.context import Role


class Action(StrEnum):
    # Organisation management
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"

    # Membership and invitations
    MEMBERSHIP_LIST = "membership:list"
    MEMBERSHIP_MUTATE = "membership:mutate"
    INVITATION_CREATE = "invitation:create"
    INVITATION_REVOKE = "invitation:revoke"
    INVITATION_LIST = "invitation:list"

    # Reconciliation and data plane
    RUN_CREATE = "run:create"
    RUN_ABORT = "run:abort"
    RUN_DELETE = "run:delete"
    RUN_VIEW = "run:view"
    INVESTIGATION_RESOLVE = "investigation:resolve"
    CERTIFICATE_ISSUE = "certificate:issue"
    AUDIT_VIEW = "audit:view"


# Immutable Capability Matrix mapping Action -> set of authorized Roles
CAPABILITY_MATRIX: Final[dict[Action, frozenset[Role]]] = {
    Action.ORG_UPDATE: frozenset({Role.OWNER}),
    Action.ORG_DELETE: frozenset({Role.OWNER}),
    Action.MEMBERSHIP_LIST: frozenset({Role.OWNER, Role.ADMIN}),
    Action.MEMBERSHIP_MUTATE: frozenset({Role.OWNER, Role.ADMIN}),
    Action.INVITATION_CREATE: frozenset({Role.OWNER, Role.ADMIN}),
    Action.INVITATION_REVOKE: frozenset({Role.OWNER, Role.ADMIN}),
    Action.INVITATION_LIST: frozenset({Role.OWNER, Role.ADMIN}),
    Action.RUN_CREATE: frozenset({Role.OWNER, Role.ADMIN, Role.OPERATOR}),
    Action.RUN_ABORT: frozenset({Role.OWNER, Role.ADMIN, Role.OPERATOR}),
    Action.RUN_DELETE: frozenset({Role.OWNER, Role.ADMIN}),
    Action.RUN_VIEW: frozenset(
        {
            Role.OWNER,
            Role.ADMIN,
            Role.OPERATOR,
            Role.REVIEWER,
            Role.AUDITOR,
        }
    ),
    Action.INVESTIGATION_RESOLVE: frozenset(
        {
            Role.OWNER,
            Role.ADMIN,
            Role.OPERATOR,
            Role.REVIEWER,
        }
    ),
    Action.CERTIFICATE_ISSUE: frozenset({Role.OWNER, Role.ADMIN, Role.REVIEWER}),
    Action.AUDIT_VIEW: frozenset(
        {
            Role.OWNER,
            Role.ADMIN,
            Role.OPERATOR,
            Role.REVIEWER,
            Role.AUDITOR,
        }
    ),
}


class PermissionDeniedError(Exception):
    """Raised when an actor lacks the required capability for an action."""

    def __init__(self, action: Action, role: Role | str | None) -> None:
        self.action = action
        self.role = role
        super().__init__(f"Role {role!r} is not authorized to perform action {action.value!r}")


def check_permission(role: Role | str, action: Action) -> bool:
    """Check if the given role is authorized to perform the action."""
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    authorized_roles = CAPABILITY_MATRIX.get(action, frozenset())
    return role in authorized_roles


def require_permission(role: Role | str | None, action: Action) -> None:
    """Enforce capability check; raises PermissionDeniedError if not authorized."""
    if role is None or not check_permission(role, action):
        raise PermissionDeniedError(action, role)


def can_manage_target_role(actor_role: Role | str, target_role: Role | str) -> bool:
    """Verify that actor role can assign, demote, or modify target role.

    Owners can manage all roles.
    Admins cannot assign or modify owners.
    Other roles cannot manage any roles.
    """
    if isinstance(actor_role, str):
        try:
            actor_role = Role(actor_role)
        except ValueError:
            return False
    if isinstance(target_role, str):
        try:
            target_role = Role(target_role)
        except ValueError:
            return False

    if actor_role == Role.OWNER:
        return True
    if actor_role == Role.ADMIN:
        return target_role != Role.OWNER
    return False

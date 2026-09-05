"""Tests for role capability matrix and permission checking."""

from __future__ import annotations

import pytest

from auth.permissions import (
    Action,
    PermissionDeniedError,
    can_manage_target_role,
    check_permission,
    require_permission,
)


def test_owner_has_all_permissions() -> None:
    for action in Action:
        assert check_permission("owner", action) is True
        require_permission("owner", action)


def test_admin_permissions_boundary() -> None:
    # Admin can perform most actions
    assert check_permission("admin", Action.RUN_CREATE) is True
    assert check_permission("admin", Action.RUN_DELETE) is True
    assert check_permission("admin", Action.MEMBERSHIP_MUTATE) is True
    assert check_permission("admin", Action.INVITATION_CREATE) is True

    # Admin cannot delete the organisation
    assert check_permission("admin", Action.ORG_DELETE) is False
    assert check_permission("admin", Action.ORG_UPDATE) is False

    # Admin cannot manage owner role
    assert can_manage_target_role("admin", "owner") is False
    assert can_manage_target_role("admin", "admin") is True
    assert can_manage_target_role("admin", "operator") is True
    assert can_manage_target_role("admin", "reviewer") is True
    assert can_manage_target_role("admin", "auditor") is True


def test_operator_permissions() -> None:
    # Operator can create/abort runs and resolve investigations
    assert check_permission("operator", Action.RUN_CREATE) is True
    assert check_permission("operator", Action.RUN_ABORT) is True
    assert check_permission("operator", Action.INVESTIGATION_RESOLVE) is True

    # Operator cannot delete runs or issue certificates
    assert check_permission("operator", Action.RUN_DELETE) is False
    assert check_permission("operator", Action.CERTIFICATE_ISSUE) is False
    assert check_permission("operator", Action.MEMBERSHIP_MUTATE) is False
    assert check_permission("operator", Action.INVITATION_CREATE) is False

    with pytest.raises(PermissionDeniedError):
        require_permission("operator", Action.MEMBERSHIP_MUTATE)


def test_reviewer_read_and_certificate() -> None:
    assert check_permission("reviewer", Action.RUN_VIEW) is True
    assert check_permission("reviewer", Action.CERTIFICATE_ISSUE) is True
    assert check_permission("reviewer", Action.INVESTIGATION_RESOLVE) is True

    # Cannot mutate runs or control plane
    assert check_permission("reviewer", Action.RUN_CREATE) is False
    assert check_permission("reviewer", Action.RUN_DELETE) is False
    assert check_permission("reviewer", Action.MEMBERSHIP_MUTATE) is False


def test_auditor_compliance_inspection() -> None:
    assert check_permission("auditor", Action.AUDIT_VIEW) is True
    assert check_permission("auditor", Action.RUN_VIEW) is True

    # Cannot mutate anything
    assert check_permission("auditor", Action.RUN_CREATE) is False
    assert check_permission("auditor", Action.CERTIFICATE_ISSUE) is False
    assert check_permission("auditor", Action.MEMBERSHIP_MUTATE) is False
    assert check_permission("auditor", Action.INVITATION_CREATE) is False


def test_null_or_unknown_role_fails_closed() -> None:
    assert check_permission(None, Action.RUN_VIEW) is False
    assert check_permission("unknown_role", Action.RUN_VIEW) is False

    with pytest.raises(PermissionDeniedError):
        require_permission(None, Action.RUN_VIEW)

"""Tests verifying that all 23 control-plane database functions exist with exact ownership and privileges."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

EXPECTED_FUNCTIONS = {
    # 1-2: OIDC flow
    "fn_oidc_create_transaction",
    "fn_oidc_consume_transaction",
    # 3: Identity resolution
    "fn_auth_resolve_federated_identity",
    # 4-9: Sessions
    "fn_auth_create_session",
    "fn_auth_lookup_session",
    "fn_auth_touch_session_throttled",
    "fn_auth_revoke_session",
    "fn_auth_revoke_all_sessions",
    "fn_auth_switch_organisation",
    # 10-11: Organisations
    "fn_org_create",
    "fn_org_list",
    # 12-13: Memberships
    "fn_membership_list",
    "fn_membership_mutate_with_mutex",
    # 14-18: Invitations
    "fn_invitation_create",
    "fn_invitation_lookup",
    "fn_invitation_accept_with_mutex",
    "fn_invitation_revoke",
    "fn_invitation_list",
    # 19: Security events
    "fn_sec_event_record",
    # 20-23: Maintenance
    "fn_maintenance_purge_security_events",
    "fn_maintenance_purge_oidc_transactions",
    "fn_maintenance_purge_expired_sessions",
    "fn_maintenance_redact_accepted_invitations",
}

MAINTENANCE_FUNCTIONS = {
    "fn_maintenance_purge_security_events",
    "fn_maintenance_purge_oidc_transactions",
    "fn_maintenance_purge_expired_sessions",
    "fn_maintenance_redact_accepted_invitations",
}

AUTH_FUNCTIONS = {
    "fn_oidc_create_transaction",
    "fn_oidc_consume_transaction",
    "fn_auth_resolve_federated_identity",
    "fn_auth_create_session",
    "fn_sec_event_record",
}

APP_FUNCTIONS = (
    EXPECTED_FUNCTIONS
    - MAINTENANCE_FUNCTIONS
    - {
        "fn_oidc_create_transaction",
        "fn_oidc_consume_transaction",
        "fn_auth_resolve_federated_identity",
        "fn_auth_create_session",
    }
)


def test_manifest_function_catalog_count() -> None:
    """Verify the exact count of functions in the specification catalogue."""
    assert len(EXPECTED_FUNCTIONS) == 23
    assert len(MAINTENANCE_FUNCTIONS) == 4
    assert len(AUTH_FUNCTIONS) == 5
    assert len(APP_FUNCTIONS) == 15


def test_postgresql_manifest_conformance(session: Session, is_postgres: bool) -> None:
    """Introspect pg_proc on PostgreSQL to verify all 23 functions exist with untangle_fn_owner ownership."""
    if not is_postgres:
        pytest.skip("Manifest introspection requires PostgreSQL")

    # 1. Verify existence and owner
    sql = text("""
        SELECT p.proname, r.rolname as owner_name
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        JOIN pg_roles r ON p.proowner = r.oid
        WHERE n.nspname = 'public' AND p.proname LIKE 'fn_%'
    """)
    rows = session.execute(sql).fetchall()
    found_functions = {r.proname: r.owner_name for r in rows}

    missing = EXPECTED_FUNCTIONS - set(found_functions.keys())
    assert not missing, f"Missing control-plane functions in PostgreSQL: {missing}"

    for fn_name in EXPECTED_FUNCTIONS:
        assert found_functions[fn_name] == "untangle_fn_owner", (
            f"Function {fn_name} must be owned by untangle_fn_owner, got {found_functions[fn_name]}"
        )

    # 2. Verify grant execution boundaries
    grant_sql = text("""
        SELECT routine_name, grantee
        FROM information_schema.role_routine_grants
        WHERE routine_schema = 'public'
          AND routine_name LIKE 'fn_%'
          AND privilege_type = 'EXECUTE'
    """)
    grant_rows = session.execute(grant_sql).fetchall()
    grants: dict[str, set[str]] = {}
    for r in grant_rows:
        grants.setdefault(r.routine_name, set()).add(r.grantee)

    # untangle_maintenance must have execute on maintenance functions only
    for m_fn in MAINTENANCE_FUNCTIONS:
        assert "untangle_maintenance" in grants.get(m_fn, set()), (
            f"{m_fn} missing EXECUTE for untangle_maintenance"
        )
        assert "untangle_app" not in grants.get(m_fn, set()), (
            f"{m_fn} should NOT be granted to untangle_app"
        )

    # untangle_app must have execute on all app functions
    for a_fn in APP_FUNCTIONS:
        assert "untangle_app" in grants.get(a_fn, set()), f"{a_fn} missing EXECUTE for untangle_app"

    # untangle_auth must have execute on auth functions
    for auth_fn in AUTH_FUNCTIONS:
        assert "untangle_auth" in grants.get(auth_fn, set()), (
            f"{auth_fn} missing EXECUTE for untangle_auth"
        )

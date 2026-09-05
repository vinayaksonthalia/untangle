"""Tests proving zero caller-supplied identity in SQL functions and least-privilege role boundaries."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from persistence.context import TenantContext


def test_functions_reject_invalid_session_token_hash(
    session: Session,
    tenant_a: tuple[TenantContext, int],
    is_postgres: bool,
) -> None:
    if not is_postgres:
        pytest.skip("PostgreSQL database functions test only")

    fake_hash = "a" * 64

    # 1. fn_org_list must return 0 rows for fake session hash
    rows = session.execute(
        text("SELECT * FROM public.fn_org_list(:hash)"),
        {"hash": fake_hash},
    ).fetchall()
    assert len(rows) == 0

    # 2. fn_membership_list must raise exception for fake session hash
    with pytest.raises(Exception, match="(?i)unauthorized|invalid"):
        session.execute(
            text("SELECT * FROM public.fn_membership_list(:hash)"),
            {"hash": fake_hash},
        ).fetchall()

    # 3. fn_invitation_create must raise exception for fake session hash
    with pytest.raises(Exception, match="(?i)unauthorized|invalid"):
        session.execute(
            text(
                "SELECT * FROM public.fn_invitation_create(:hash, 'test@example.com', 'reviewer', 'tok_hash', 'ivt_pub', 604800, 'aud_pub')"
            ),
            {"hash": fake_hash},
        ).fetchall()


def test_untangle_app_cannot_query_control_plane_tables_directly(
    session_factory,
    is_postgres: bool,
) -> None:
    """Verify that untangle_app role cannot directly SELECT from sensitive control plane tables."""
    if not is_postgres:
        pytest.skip("Role privilege test requires PostgreSQL with untangle_app role")

    with session_factory() as app_session:
        for table in (
            "principals",
            "organisations",
            "organisation_memberships",
            "user_sessions",
            "trusted_auth_issuers",
            "federated_identities",
            "oidc_auth_transactions",
            "control_plane_security_events",
        ):
            with pytest.raises(Exception, match="(?i)permission denied"):
                app_session.execute(text(f"SELECT * FROM public.{table} LIMIT 1"))
                app_session.commit()

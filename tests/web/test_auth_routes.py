"""Tests for authentication and control plane API routes."""

from __future__ import annotations

import urllib.parse

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth.crypto import generate_csrf_token, hash_token
from auth.sessions import create_session, lookup_session
from persistence.context import Role, TenantContext
from persistence.models import TrustedAuthIssuer
from webapp.auth_routes import (
    CSRF_COOKIE_NAME,
    create_session_with_default_organisation,
    safe_return_to,
)


def test_safe_return_to_accepts_only_same_site_paths() -> None:
    assert safe_return_to("/dashboard") == "/dashboard"
    assert safe_return_to("/app?tab=cases") == "/app?tab=cases"
    for candidate in ("", "https://attacker.test", "//attacker.test", "/\\attacker.test"):
        assert safe_return_to(candidate) == "/dashboard"


def test_callback_session_selects_the_only_active_organisation(
    session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token = create_session_with_default_organisation(
        session,
        session,
        principal_id=ctx.principal_id,
        ip_address="127.0.0.1",
        user_agent="test",
    )
    info = lookup_session(session, raw_token)
    assert info is not None
    assert info.active_organisation_id == org_id


def test_auth_login_redirect_and_cookie(client: TestClient, seed_issuer: TrustedAuthIssuer) -> None:
    resp = client.get("/api/auth/login?return_to=/app", follow_redirects=False)
    assert resp.status_code == 302
    assert "https://auth.untangle.internal/authorize" in resp.headers["location"]
    assert "untangle_oidc_state" in resp.cookies


def test_auth_login_json_response(client: TestClient, seed_issuer: TrustedAuthIssuer) -> None:
    resp = client.get("/api/auth/login", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert "authorization_url" in data
    assert "state" in data
    assert "untangle_oidc_state" in resp.cookies


def test_auth_me_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False}


def test_auth_me_authenticated(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    client.cookies.set("untangle_session", raw_token)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["principal"]["email"] == "alice@alpha.test"
    assert data["organisation"]["id"] == org_id
    assert data["organisation"]["role"] == Role.OWNER.value
    assert len(data["capabilities"]) > 0


def test_auth_logout_clears_cookies(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)
    secret_key = "test-secret-key-12345678901234567890"
    csrf_token = generate_csrf_token(secret_key, token_hash)

    client.cookies.set("untangle_session", raw_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)

    headers = {
        "origin": "http://localhost:8080",
        "x-csrf-token": csrf_token,
    }
    resp = client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged_out"}


def test_org_management_endpoints(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)
    secret_key = "test-secret-key-12345678901234567890"
    csrf_token = generate_csrf_token(secret_key, token_hash)

    client.cookies.set("untangle_session", raw_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)

    headers = {
        "origin": "http://localhost:8080",
        "x-csrf-token": csrf_token,
    }

    # 1. List orgs
    resp_list = client.get("/api/orgs")
    assert resp_list.status_code == 200
    orgs = resp_list.json()
    assert len(orgs) >= 1
    assert orgs[0]["org_id"] == org_id

    # 2. Create new org
    resp_create = client.post(
        "/api/orgs/create", json={"name": "Organisation Delta"}, headers=headers
    )
    assert resp_create.status_code == 200
    new_org_data = resp_create.json()
    assert new_org_data["status"] == "created"
    assert new_org_data["name"] == "Organisation Delta"
    assert new_org_data["role"] == Role.OWNER.value


def test_member_and_invitation_endpoints(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    token_hash = hash_token(raw_token)
    secret_key = "test-secret-key-12345678901234567890"
    csrf_token = generate_csrf_token(secret_key, token_hash)

    client.cookies.set("untangle_session", raw_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)

    headers = {
        "origin": "http://localhost:8080",
        "x-csrf-token": csrf_token,
    }

    # 1. List members
    resp_members = client.get("/api/orgs/members")
    assert resp_members.status_code == 200
    members = resp_members.json()
    assert len(members) >= 1

    # 2. Create invitation
    resp_invite = client.post(
        "/api/orgs/invitations",
        json={"email": "newbie@example.com", "role_code": "reviewer"},
        headers=headers,
    )
    assert resp_invite.status_code == 200
    inv_data = resp_invite.json()
    assert inv_data["status"] == "invited"
    assert inv_data["email"] == "newbie@example.com"
    assert "invitation_link" in inv_data  # Loopback dev mode exposes link

    # Extract token from invitation_link
    parsed = urllib.parse.urlparse(inv_data["invitation_link"])
    token = urllib.parse.parse_qs(parsed.query)["token"][0]

    # 3. Public lookup of invitation
    resp_lookup = client.get(f"/api/invitations/lookup?token={token}")
    assert resp_lookup.status_code == 200
    lookup_data = resp_lookup.json()
    assert lookup_data["email"] == "newbie@example.com"
    assert lookup_data["role"] == "reviewer"
    assert not lookup_data["is_expired"]

    # 4. List pending invitations
    resp_inv_list = client.get("/api/orgs/invitations")
    assert resp_inv_list.status_code == 200
    assert len(resp_inv_list.json()) >= 1

    # 5. Revoke invitation
    resp_revoke = client.post(
        "/api/orgs/invitations/revoke",
        json={"invitation_public_id": inv_data["public_id"]},
        headers=headers,
    )
    assert resp_revoke.status_code == 200
    assert resp_revoke.json() == {"status": "revoked", "public_id": inv_data["public_id"]}

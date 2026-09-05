"""Tests for CSRF origin allowlist and session-bound double-submit tokens."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth.crypto import generate_csrf_token, hash_token
from auth.sessions import create_session
from persistence.context import TenantContext
from webapp.auth_routes import CSRF_COOKIE_NAME


def test_safe_methods_bypass_csrf(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200


def test_public_demo_unauthenticated_post_bypasses_csrf(client: TestClient) -> None:
    # Public verify endpoint called without session cookie or origin header
    resp = client.post("/api/verify", json={"certificate_version": 1})
    # Should not be blocked with 403 CSRF error
    assert resp.status_code != 403


def test_control_plane_mutating_missing_origin_rejected(client: TestClient) -> None:
    # POST to /api/auth/logout without Origin or Referer header
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 403
    data = resp.json()
    assert data.get("error") == "CSRF_ORIGIN_MISSING"


def test_control_plane_mutating_disallowed_origin_rejected(client: TestClient) -> None:
    headers = {"origin": "https://evil-attacker.com"}
    resp = client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 403
    data = resp.json()
    assert data.get("error") == "CSRF_ORIGIN_DENIED"


def test_authenticated_mutating_missing_csrf_token_rejected(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    client.cookies.set("untangle_session", raw_token)
    headers = {"origin": "http://localhost:8080"}

    # Authenticated mutating request without X-CSRF-Token
    resp = client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 403
    assert resp.json().get("error") == "CSRF_TOKEN_MISSING"


def test_authenticated_mutating_invalid_csrf_token_rejected(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    client.cookies.set("untangle_session", raw_token)
    headers = {
        "origin": "http://localhost:8080",
        "x-csrf-token": "completely-invalid-csrf-token-xyz",
    }

    resp = client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 403
    assert resp.json().get("error") == "CSRF_TOKEN_INVALID"


def test_authenticated_mutating_valid_csrf_token_accepted(
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

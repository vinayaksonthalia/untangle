"""Tests for TenantRouteGuard middleware failing closed on tenant resources."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth.sessions import create_session
from persistence.context import Role, TenantContext
from webapp.app import app

# Add a dummy tenant-isolated route for testing the guard
tenant_test_router = APIRouter(prefix="/api/tenant")


@tenant_test_router.get("/data")
def get_tenant_data(request: Request) -> JSONResponse:
    tenant_ctx: TenantContext | None = getattr(request.state, "tenant_context", None)
    if not tenant_ctx:
        return JSONResponse({"error": "no_ctx"}, status_code=500)
    return JSONResponse(
        {
            "status": "ok",
            "organisation_id": tenant_ctx.organisation_id,
            "principal_id": tenant_ctx.principal_id,
            "role": tenant_ctx.role.value,
        }
    )


app.include_router(tenant_test_router)


def test_tenant_route_unauthenticated_returns_401(client: TestClient) -> None:
    resp = client.get("/api/tenant/data")
    assert resp.status_code == 401
    assert resp.json().get("error") == "UNAUTHENTICATED"


def test_tenant_route_no_active_org_returns_403(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, _ = tenant_a
    # Create session WITHOUT an active organisation
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=None)

    client.cookies.set("untangle_session", raw_token)
    resp = client.get("/api/tenant/data")
    assert resp.status_code == 403
    assert resp.json().get("error") == "NO_ACTIVE_ORGANISATION"


def test_tenant_route_with_active_org_allowed(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    # Create session WITH active organisation
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)

    client.cookies.set("untangle_session", raw_token)
    resp = client.get("/api/tenant/data")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["organisation_id"] == org_id
    assert data["role"] == Role.OWNER.value

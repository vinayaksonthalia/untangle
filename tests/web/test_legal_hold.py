"""Tests for legal hold placing/releasing and deletion protection."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from auth.sessions import create_session
from persistence.context import Role, TenantContext
from tests.web.conftest import auth_headers


def _create_test_run(
    client: TestClient,
    raw_token: str,
    sample_file_bytes: tuple[bytes, bytes, bytes],
    idemp_key: str,
) -> str:
    """Helper to submit a run and return its run_id."""
    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = idemp_key
    b_data, r_data, l_data = sample_file_bytes
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 202
    return resp.json()["run_id"]


def test_legal_hold_lifecycle_and_deletion_protection(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    run_id = _create_test_run(client, raw_token, sample_file_bytes, "idemp_legal_001")

    # 1. Place legal hold
    headers = auth_headers(raw_token)
    resp_hold = client.post(
        f"/api/tenant/runs/{run_id}/legal-hold",
        headers=headers,
        json={"legal_hold": True},
    )
    assert resp_hold.status_code == 200
    assert resp_hold.json() == {"id": run_id, "legal_hold": True}

    # Verify run detail reflects legal hold
    resp_detail = client.get(f"/api/tenant/runs/{run_id}")
    assert resp_detail.status_code == 200
    assert resp_detail.json()["legal_hold"] is True

    # 2. Attempt deletion while under legal hold -> 409 Conflict
    del_headers = auth_headers(raw_token)
    resp_del_blocked = client.delete(f"/api/tenant/runs/{run_id}", headers=del_headers)
    assert resp_del_blocked.status_code == 409
    assert "legal hold" in resp_del_blocked.json()["detail"].lower()

    # 3. Release legal hold
    resp_release = client.post(
        f"/api/tenant/runs/{run_id}/legal-hold",
        headers=headers,
        json={"legal_hold": False},
    )
    assert resp_release.status_code == 200
    assert resp_release.json() == {"id": run_id, "legal_hold": False}

    # Verify run detail reflects release
    resp_detail2 = client.get(f"/api/tenant/runs/{run_id}")
    assert resp_detail2.status_code == 200
    assert resp_detail2.json()["legal_hold"] is False

    # 4. Now deletion succeeds -> 200
    resp_del = client.delete(f"/api/tenant/runs/{run_id}", headers=del_headers)
    assert resp_del.status_code == 200
    assert resp_del.json() == {"id": run_id, "deleted": True}

    # 5. Subsequent queries for soft-deleted run return 404
    resp_after = client.get(f"/api/tenant/runs/{run_id}")
    assert resp_after.status_code == 404

    # 6. Attempting to delete already deleted run returns 404
    resp_del_again = client.delete(f"/api/tenant/runs/{run_id}", headers=del_headers)
    assert resp_del_again.status_code == 404


def test_legal_hold_and_deletion_rbac_enforcement(
    client: TestClient,
    session: Session,
    seed_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    # Create run as owner
    raw_token_owner, _ = create_session(
        session, principal_id=ctx.principal_id, active_org_id=org_id
    )
    client.cookies.set("untangle_session", raw_token_owner)
    run_id = _create_test_run(client, raw_token_owner, sample_file_bytes, "idemp_legal_rbac_001")

    # Create an auditor user in Tenant A
    from persistence.repositories.control_plane import create_membership, create_principal

    with seed_session_factory() as seed:
        auditor_user = create_principal(seed, "auditor@alpha.test", "Auditor Alice")
        create_membership(seed, org_id, auditor_user.id, Role.AUDITOR)
        seed.commit()
        auditor_principal_id = auditor_user.id

    # Switch session to Auditor
    raw_token_auditor, _ = create_session(
        session, principal_id=auditor_principal_id, active_org_id=org_id
    )
    client.cookies.set("untangle_session", raw_token_auditor)

    headers_auditor = auth_headers(raw_token_auditor)

    # Auditor attempting to place legal hold -> 403 Forbidden
    resp_hold = client.post(
        f"/api/tenant/runs/{run_id}/legal-hold",
        headers=headers_auditor,
        json={"legal_hold": True},
    )
    assert resp_hold.status_code == 403

    # Auditor attempting to delete run -> 403 Forbidden
    resp_del = client.delete(f"/api/tenant/runs/{run_id}", headers=headers_auditor)
    assert resp_del.status_code == 403


def test_legal_hold_cross_tenant_rejection(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    tenant_b: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx_a, org_a_id = tenant_a
    ctx_b, org_b_id = tenant_b

    # Tenant A creates a run
    raw_token_a, _ = create_session(
        session, principal_id=ctx_a.principal_id, active_org_id=org_a_id
    )
    client.cookies.set("untangle_session", raw_token_a)
    run_a_id = _create_test_run(client, raw_token_a, sample_file_bytes, "idemp_legal_tenant_a")

    # Tenant B tries to place legal hold on Tenant A's run -> 404
    raw_token_b, _ = create_session(
        session, principal_id=ctx_b.principal_id, active_org_id=org_b_id
    )
    client.cookies.set("untangle_session", raw_token_b)
    headers_b = auth_headers(raw_token_b)

    resp_b_hold = client.post(
        f"/api/tenant/runs/{run_a_id}/legal-hold",
        headers=headers_b,
        json={"legal_hold": True},
    )
    assert resp_b_hold.status_code == 404

    # Tenant B tries to delete Tenant A's run -> 404
    resp_b_del = client.delete(f"/api/tenant/runs/{run_a_id}", headers=headers_b)
    assert resp_b_del.status_code == 404

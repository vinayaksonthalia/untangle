"""Comprehensive test suite for tenant reconciliation routes, background execution, and isolation."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from auth.sessions import create_session
from persistence.context import TenantContext
from persistence.models import ReconciliationJob
from persistence.worker import BackgroundWorkerService
from tests.web.conftest import auth_headers


@pytest.fixture(autouse=True)
def clean_queued_jobs(web_session_factory: sessionmaker[Session]):
    with web_session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(
                status="completed",
                stage="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        s.commit()
    yield
    with web_session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(
                status="completed",
                stage="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        s.commit()


def test_reconcile_unauthenticated_returns_401(client: TestClient) -> None:
    resp = client.post("/api/tenant/reconcile")
    assert resp.status_code == 401
    assert resp.json().get("error") == "UNAUTHENTICATED"


def test_reconcile_no_active_org_returns_403(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, _ = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=None)
    client.cookies.set("untangle_session", raw_token)

    headers = auth_headers(raw_token)
    resp = client.post("/api/tenant/reconcile", headers=headers)
    assert resp.status_code == 403
    assert resp.json().get("error") == "NO_ACTIVE_ORGANISATION"


def test_reconcile_missing_files_returns_422(
    client: TestClient, session: Session, tenant_a: tuple[TenantContext, int]
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    headers = auth_headers(raw_token)
    # Post with only bank file
    files = {"bank": ("bank.csv", b"sample content", "text/csv")}
    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 422
    assert "Missing required file" in resp.json().get("detail", "")


def test_reconcile_invalid_dates_returns_422(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)
    b_data, r_data, l_data = sample_file_bytes

    headers = auth_headers(raw_token)
    headers["X-Period-Start"] = "invalid-date"
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 422

    # start > end
    headers["X-Period-Start"] = "2026-06-30"
    headers["X-Period-End"] = "2026-06-01"
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 422
    assert "earlier than or equal to" in resp.json().get("detail", "")


def test_reconcile_submission_idempotency_and_cancellation(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)
    b_data, r_data, l_data = sample_file_bytes

    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = "idemp_key_test_001"
    headers["X-Period-Start"] = "2026-04-01"
    headers["X-Period-End"] = "2026-04-30"
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }

    # 1. First submission -> 202 Accepted
    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 202
    assert "Idempotent-Replay" not in resp.headers
    data = resp.json()
    job_id = data["job_id"]
    run_id = data["run_id"]
    assert data["status"] == "queued"
    assert data["stage"] == "queued"
    assert data["links"]["status"] == f"/api/tenant/jobs/{job_id}"
    assert data["links"]["cancel"] == f"/api/tenant/jobs/{job_id}/cancel"
    assert data["links"]["run"] == f"/api/tenant/runs/{run_id}"

    # 2. Replay with exact same files and key -> 202 with Idempotent-Replay header
    files_replay = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp_replay = client.post("/api/tenant/reconcile", headers=headers, files=files_replay)
    assert resp_replay.status_code == 202
    assert resp_replay.headers.get("Idempotent-Replay") == "true"
    assert resp_replay.json()["job_id"] == job_id

    # 3. Collision with same key but altered payload -> 409 Conflict
    files_diff = {
        "bank": ("bank_statement.csv", b"different bytes", "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp_collision = client.post("/api/tenant/reconcile", headers=headers, files=files_diff)
    assert resp_collision.status_code == 409

    # 4. Check job status endpoint
    resp_job = client.get(f"/api/tenant/jobs/{job_id}")
    assert resp_job.status_code == 200
    job_info = resp_job.json()
    assert job_info["id"] == job_id
    assert job_info["run_id"] == run_id
    assert job_info["status"] == "queued"

    # 5. Check run detail endpoint
    resp_run = client.get(f"/api/tenant/runs/{run_id}")
    assert resp_run.status_code == 200
    run_info = resp_run.json()
    assert run_info["id"] == run_id
    assert run_info["status"] == "initiated"
    assert run_info["reporting_period_start"] == "2026-04-01"
    assert run_info["reporting_period_end"] == "2026-04-30"

    # 6. Request job cancellation
    cancel_headers = auth_headers(raw_token)
    resp_cancel = client.post(f"/api/tenant/jobs/{job_id}/cancel", headers=cancel_headers)
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["cancelled"] is True


def test_cursor_pagination_runs(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)
    b_data, r_data, l_data = sample_file_bytes

    # Submit 3 distinct runs
    for i in range(3):
        headers = auth_headers(raw_token)
        headers["Idempotency-Key"] = f"idemp_pagination_{i}"
        files = {
            "bank": ("bank_statement.csv", b_data, "text/csv"),
            "recon": ("recon_report.json", r_data, "application/json"),
            "ledger": ("order_ledger.csv", l_data, "text/csv"),
        }
        resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
        assert resp.status_code == 202

    # Query with limit=2
    resp_p1 = client.get("/api/tenant/runs?limit=2")
    assert resp_p1.status_code == 200
    p1_data = resp_p1.json()
    assert len(p1_data["items"]) == 2
    assert p1_data["next_cursor"] is not None

    # Query page 2 with cursor
    cursor = p1_data["next_cursor"]
    resp_p2 = client.get(f"/api/tenant/runs?limit=2&cursor={cursor}")
    assert resp_p2.status_code == 200
    p2_data = resp_p2.json()
    assert len(p2_data["items"]) >= 1
    # Check item IDs are disjoint
    p1_ids = {item["id"] for item in p1_data["items"]}
    p2_ids = {item["id"] for item in p2_data["items"]}
    assert p1_ids.isdisjoint(p2_ids)


def test_full_worker_processing_and_artifact_endpoints(
    client: TestClient,
    session: Session,
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
    web_session_factory: sessionmaker[Session],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)
    b_data, r_data, l_data = sample_file_bytes

    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = "idemp_worker_test_001"
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }

    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 202
    data = resp.json()
    job_id = data["job_id"]
    run_id = data["run_id"]

    # Execute worker cycle to process this job
    worker = BackgroundWorkerService(
        worker_session_factory=web_session_factory,
        app_session_factory=web_session_factory,
    )
    processed = worker.process_next_job()
    assert processed is True

    # Check job is now completed
    resp_job = client.get(f"/api/tenant/jobs/{job_id}")
    assert resp_job.status_code == 200
    assert resp_job.json()["status"] == "completed"

    # 1. GET /api/tenant/runs/{id}/presentation
    resp_pres = client.get(f"/api/tenant/runs/{run_id}/presentation")
    assert resp_pres.status_code == 200
    pres_data = resp_pres.json()
    assert "summary" in pres_data
    assert "run_identity" in pres_data

    # 2. GET /api/tenant/runs/{id}/investigations
    resp_inv = client.get(f"/api/tenant/runs/{run_id}/investigations")
    assert resp_inv.status_code == 200
    inv_data = resp_inv.json()
    assert "summary" in inv_data
    assert "cases" in inv_data

    # 3. GET /api/tenant/runs/{id}/certificate
    resp_cert = client.get(f"/api/tenant/runs/{run_id}/certificate")
    assert resp_cert.status_code == 200
    cert_data = resp_cert.json()
    assert "certificate" in cert_data

    # 4. GET /api/tenant/runs/{id}/artifacts/tally_xml
    resp_tally = client.get(f"/api/tenant/runs/{run_id}/artifacts/tally_xml")
    assert resp_tally.status_code == 200
    assert "xml" in resp_tally.headers.get("content-type", "").lower()
    assert b"<ENVELOPE>" in resp_tally.content or b"<TALLYMESSAGE" in resp_tally.content

    # 5. GET /api/tenant/runs/{id}/artifacts/report_json
    resp_rep = client.get(f"/api/tenant/runs/{run_id}/artifacts/report_json")
    assert resp_rep.status_code == 200
    assert "json" in resp_rep.headers.get("content-type", "").lower()

    # 6. GET unknown artifact -> 404
    resp_unk = client.get(f"/api/tenant/runs/{run_id}/artifacts/nonexistent_artifact")
    assert resp_unk.status_code == 404


def test_cross_tenant_isolation(
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
    b_data, r_data, l_data = sample_file_bytes

    headers_a = auth_headers(raw_token_a)
    headers_a["Idempotency-Key"] = "idemp_tenant_a_001"
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp_a = client.post("/api/tenant/reconcile", headers=headers_a, files=files)
    assert resp_a.status_code == 202
    job_a_id = resp_a.json()["job_id"]
    run_a_id = resp_a.json()["run_id"]

    # Now switch client session to Tenant B
    raw_token_b, _ = create_session(
        session, principal_id=ctx_b.principal_id, active_org_id=org_b_id
    )
    client.cookies.set("untangle_session", raw_token_b)

    # Tenant B tries to access Tenant A's job -> 404
    resp_b_job = client.get(f"/api/tenant/jobs/{job_a_id}")
    assert resp_b_job.status_code == 404

    # Tenant B tries to cancel Tenant A's job -> 404
    headers_b = auth_headers(raw_token_b)
    resp_b_cancel = client.post(f"/api/tenant/jobs/{job_a_id}/cancel", headers=headers_b)
    assert resp_b_cancel.status_code == 404

    # Tenant B tries to access Tenant A's run -> 404
    resp_b_run = client.get(f"/api/tenant/runs/{run_a_id}")
    assert resp_b_run.status_code == 404

    # Tenant B tries to access Tenant A's presentation -> 404
    resp_b_pres = client.get(f"/api/tenant/runs/{run_a_id}/presentation")
    assert resp_b_pres.status_code == 404

    # Tenant B tries to access Tenant A's artifacts -> 404
    resp_b_art = client.get(f"/api/tenant/runs/{run_a_id}/artifacts/report_json")
    assert resp_b_art.status_code == 404

"""Web API integration tests for Untany Advisory Agent endpoint."""

from __future__ import annotations

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
            .values(status="completed", stage="completed")
        )
        s.commit()
    yield
    with web_session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(status="completed", stage="completed")
        )
        s.commit()


def test_agent_query_api_route_integration(
    client: TestClient,
    session: Session,
    web_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    # Submit and complete a run
    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = "idemp_agent_route_001"
    headers["X-Period-Start"] = "2026-04-01"
    headers["X-Period-End"] = "2026-04-30"
    b_data, r_data, l_data = sample_file_bytes
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp_init = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp_init.status_code == 202
    run_id = resp_init.json()["run_id"]

    worker = BackgroundWorkerService(
        app_session_factory=web_session_factory,
        worker_session_factory=web_session_factory,
    )
    processed = worker.process_next_job()
    assert processed is True

    # 1. Successful factual inquiry
    query_headers = auth_headers(raw_token)
    resp_query = client.post(
        "/api/tenant/agent/query",
        headers=query_headers,
        json={"run_id": run_id, "query": "What is the total reconciled amount?"},
    )
    assert resp_query.status_code == 200
    data = resp_query.json()
    assert data["status"] == "answered"
    assert data["run_id"] == run_id
    assert "reconciled" in data["answer"].lower()

    # 2. Mutating request refused via API
    resp_refused = client.post(
        "/api/tenant/agent/query",
        headers=query_headers,
        json={"run_id": run_id, "query": "Please approve the journal entry and move the funds"},
    )
    assert resp_refused.status_code == 200
    ref_data = resp_refused.json()
    assert ref_data["status"] == "refused"
    assert "read-only" in ref_data["refusal_reason"].lower()

    # 3. Nonexistent run returns 404
    resp_404 = client.post(
        "/api/tenant/agent/query",
        headers=query_headers,
        json={"run_id": "run_nonexistent_12345", "query": "What are the totals?"},
    )
    assert resp_404.status_code == 404

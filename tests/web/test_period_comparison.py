"""Tests for strict non-overlapping multi-month run comparison."""

from __future__ import annotations

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
    now = datetime.now(UTC)
    with web_session_factory() as s:
        s.execute(
            update(ReconciliationJob)
            .where(ReconciliationJob.status.in_(("queued", "running")))
            .values(
                status="completed",
                stage="completed",
                started_at=now,
                completed_at=now,
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
                started_at=now,
                completed_at=now,
            )
        )
        s.commit()


def _submit_and_complete_run(
    client: TestClient,
    raw_token: str,
    web_session_factory: sessionmaker[Session],
    sample_file_bytes: tuple[bytes, bytes, bytes],
    start_date: str,
    end_date: str,
    idemp_key: str,
) -> str:
    """Submit a reconciliation job with specified reporting period and run worker until completed."""
    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = idemp_key
    headers["X-Period-Start"] = start_date
    headers["X-Period-End"] = end_date

    b_data, r_data, l_data = sample_file_bytes
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }

    resp = client.post("/api/tenant/reconcile", headers=headers, files=files)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    worker = BackgroundWorkerService(
        app_session_factory=web_session_factory,
        worker_session_factory=web_session_factory,
    )
    processed = worker.process_next_job()
    assert processed is True
    return run_id


def test_non_overlapping_run_comparison_success(
    client: TestClient,
    session: Session,
    web_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    # April 2026 run
    run_apr = _submit_and_complete_run(
        client,
        raw_token,
        web_session_factory,
        sample_file_bytes,
        "2026-04-01",
        "2026-04-30",
        "idemp_comp_apr",
    )
    # May 2026 run
    run_may = _submit_and_complete_run(
        client,
        raw_token,
        web_session_factory,
        sample_file_bytes,
        "2026-05-01",
        "2026-05-31",
        "idemp_comp_may",
    )

    headers = auth_headers(raw_token)
    resp = client.post(
        "/api/tenant/runs/compare",
        headers=headers,
        json={"base_run_id": run_apr, "target_run_id": run_may},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["base_run"]["id"] == run_apr
    assert data["target_run"]["id"] == run_may
    assert data["period_relationship"] == "subsequent"

    deltas = data["deltas"]
    assert "total_credit_delta_paise" in deltas
    assert "reconciled_delta_paise" in deltas
    assert "unresolved_delta_paise" in deltas
    assert "fee_gst_recoverable_delta_paise" in deltas
    assert isinstance(deltas["total_credit_delta_paise"], int)

    assert "rails_comparison" in data
    assert isinstance(data["rails_comparison"], list)

    assert "root_cause_drift" in data
    assert isinstance(data["root_cause_drift"], list)


def test_overlapping_run_comparison_rejected_422(
    client: TestClient,
    session: Session,
    web_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    # Period 1: April 1 to April 30
    run1 = _submit_and_complete_run(
        client,
        raw_token,
        web_session_factory,
        sample_file_bytes,
        "2026-04-01",
        "2026-04-30",
        "idemp_overlap_1",
    )
    # Period 2: April 15 to May 15 (overlaps Period 1)
    run2 = _submit_and_complete_run(
        client,
        raw_token,
        web_session_factory,
        sample_file_bytes,
        "2026-04-15",
        "2026-05-15",
        "idemp_overlap_2",
    )

    headers = auth_headers(raw_token)
    resp = client.post(
        "/api/tenant/runs/compare",
        headers=headers,
        json={"base_run_id": run1, "target_run_id": run2},
    )
    assert resp.status_code == 422
    assert "non-overlapping" in resp.json()["detail"].lower()


def test_uncompleted_run_comparison_rejected_409(
    client: TestClient,
    session: Session,
    web_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx, org_id = tenant_a
    raw_token, _ = create_session(session, principal_id=ctx.principal_id, active_org_id=org_id)
    client.cookies.set("untangle_session", raw_token)

    # Run 1 completed
    run1 = _submit_and_complete_run(
        client,
        raw_token,
        web_session_factory,
        sample_file_bytes,
        "2026-04-01",
        "2026-04-30",
        "idemp_uncomp_1",
    )

    # Run 2 submitted but NOT processed by worker (remains queued)
    headers = auth_headers(raw_token)
    headers["Idempotency-Key"] = "idemp_uncomp_2"
    headers["X-Period-Start"] = "2026-05-01"
    headers["X-Period-End"] = "2026-05-31"
    b_data, r_data, l_data = sample_file_bytes
    files = {
        "bank": ("bank_statement.csv", b_data, "text/csv"),
        "recon": ("recon_report.json", r_data, "application/json"),
        "ledger": ("order_ledger.csv", l_data, "text/csv"),
    }
    resp2 = client.post("/api/tenant/reconcile", headers=headers, files=files)
    run2 = resp2.json()["run_id"]

    resp = client.post(
        "/api/tenant/runs/compare",
        headers=headers,
        json={"base_run_id": run1, "target_run_id": run2},
    )
    assert resp.status_code == 409
    assert "not completed" in resp.json()["detail"].lower()


def test_cross_tenant_comparison_rejected_404(
    client: TestClient,
    session: Session,
    web_session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    tenant_b: tuple[TenantContext, int],
    sample_file_bytes: tuple[bytes, bytes, bytes],
) -> None:
    ctx_a, org_a_id = tenant_a
    ctx_b, org_b_id = tenant_b

    # Tenant A creates completed run
    raw_token_a, _ = create_session(
        session, principal_id=ctx_a.principal_id, active_org_id=org_a_id
    )
    client.cookies.set("untangle_session", raw_token_a)
    run_a = _submit_and_complete_run(
        client,
        raw_token_a,
        web_session_factory,
        sample_file_bytes,
        "2026-04-01",
        "2026-04-30",
        "idemp_cross_a",
    )

    # Tenant B creates completed run
    raw_token_b, _ = create_session(
        session, principal_id=ctx_b.principal_id, active_org_id=org_b_id
    )
    client.cookies.set("untangle_session", raw_token_b)
    run_b = _submit_and_complete_run(
        client,
        raw_token_b,
        web_session_factory,
        sample_file_bytes,
        "2026-05-01",
        "2026-05-31",
        "idemp_cross_b",
    )

    # Tenant B tries to compare Tenant A's run with Tenant B's run -> 404 (Tenant B cannot see Tenant A's run)
    headers_b = auth_headers(raw_token_b)
    resp = client.post(
        "/api/tenant/runs/compare",
        headers=headers_b,
        json={"base_run_id": run_a, "target_run_id": run_b},
    )
    assert resp.status_code == 404

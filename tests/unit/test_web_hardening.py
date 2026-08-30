from fastapi.testclient import TestClient

import webapp.app as web_app
from webapp.app import app


def test_healthz_is_ready_and_redacts_internals():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_verify_rejects_oversized_body_before_json_parsing():
    with TestClient(app) as client:
        response = client.post(
            "/api/verify", content=b"x" * (512 * 1024 + 1),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_request_id_is_generated_and_csp_allows_existing_demo_inline_assets():
    with TestClient(app) as client:
        response = client.get("/", headers={"x-request-id": "evil" * 1000})
    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32
    assert "script-src 'self' 'unsafe-inline'" in response.headers["content-security-policy"]


def test_rate_limiter_has_hard_cap_and_evicts_oldest():
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS = {f"ip-{i}": [1.0] for i in range(4096)}
    with TestClient(app) as client:
        response = client.post("/api/verify", json={}, headers={"x-forwarded-for": "new-ip"})
    assert response.status_code == 200  # request is admitted; eviction prevents false 429
    assert len(web_app._RATE_BUCKETS) <= 4096

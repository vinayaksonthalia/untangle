from fastapi.testclient import TestClient

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

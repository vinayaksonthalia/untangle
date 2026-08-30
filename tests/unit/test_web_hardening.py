import asyncio
import os
import tempfile
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import webapp.app as web_app
from webapp.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_healthz_is_ready_and_redacts_internals(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_verify_rejects_oversized_body_before_json_parsing(client):
    response = client.post(
        "/api/verify", content=b"x" * (512 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_request_id_is_generated_and_csp_allows_existing_demo_inline_assets(client):
    response = client.get("/", headers={"x-request-id": "evil" * 1000})
    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32
    assert "script-src 'self' 'unsafe-inline'" in response.headers["content-security-policy"]


def test_rate_limiter_has_hard_cap_and_evicts_oldest(client):
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS = {f"ip-{i}": [time.monotonic()] for i in range(4096)}
    response = client.post("/api/verify", json={}, headers={"x-forwarded-for": "new-ip"})
    assert response.status_code == 200  # request is admitted; eviction prevents false 429
    assert len(web_app._RATE_BUCKETS) <= 4096


def test_twenty_first_verify_request_is_rate_limited(client):
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS = {}
    responses = [client.post("/api/verify", json={}) for _ in range(21)]
    assert responses[-1].status_code == 429
    assert responses[-1].headers["x-content-type-options"] == "nosniff"


def test_mcp_path_is_not_counted_by_web_limiter(client):
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS = {}
    client.get("/mcp")
    assert not web_app._RATE_BUCKETS


def test_saturated_reconcile_returns_503():
    paths = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("b", "r", "l"):
            path = os.path.join(tmp, name)
            open(path, "wb").close()
            paths.append(path)
        web_app._RECONCILE_SEMAPHORE.acquire()
        web_app._RECONCILE_SEMAPHORE.acquire()
        try:
            with pytest.raises(HTTPException) as caught:
                web_app._run_safely(tmp, *paths)
            assert caught.value.status_code == 503
        finally:
            web_app._RECONCILE_SEMAPHORE.release()
            web_app._RECONCILE_SEMAPHORE.release()


def test_timeout_keeps_worker_inputs_until_release(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    observed = []

    def blocked(bank, *_args):
        with open(bank, "rb") as fh:
            observed.append(fh.read())
        started.set()
        release.wait(2)
        return {}

    monkeypatch.setattr(web_app, "reconcile", blocked)
    old_timeout = web_app._RECONCILE_TIMEOUT_SECONDS
    web_app._RECONCILE_TIMEOUT_SECONDS = 0.02
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, content in (("b", b"bank"), ("r", b"recon"), ("l", b"ledger")):
                path = os.path.join(tmp, name)
                with open(path, "wb") as fh:
                    fh.write(content)
                paths.append(path)
            with pytest.raises(HTTPException) as caught:
                asyncio.run(web_app._run_safely_async(tmp, *paths))
            assert caught.value.status_code == 504
            assert started.wait(1)
            assert observed == [b"bank"]
            release.set()
            time.sleep(0.05)
    finally:
        web_app._RECONCILE_TIMEOUT_SECONDS = old_timeout

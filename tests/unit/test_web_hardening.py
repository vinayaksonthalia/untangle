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
    # Do not enter lifespan here: test_mcp_http owns FastMCP's single-use session manager and
    # pytest may collect/run this module before or after it. Middleware tests need no lifespan.
    yield TestClient(app, raise_server_exceptions=False)


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


def test_chunked_upload_without_content_length_is_capped(client):
    # A streamed (Content-Length-less) body must still be bounded by counting ASGI bytes, or a
    # chunked request could spool an unbounded multipart body before per-file checks (Qodo #36).
    over = 512 * 1024 + 1

    def _chunks():
        sent = 0
        while sent < over:
            step = min(64 * 1024, over - sent)
            sent += step
            yield b"x" * step

    response = client.post(
        "/api/verify", content=_chunks(),
        headers={"content-type": "application/json"},  # httpx streams chunked, no content-length
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"


def test_rate_limit_decided_before_body_is_buffered(client, monkeypatch):
    # An already-rate-limited client must get 429 without the body-size middleware first ingesting
    # the payload — the admission decision precedes body consumption (Qodo #36).
    monkeypatch.setattr(web_app, "_RATE_BUCKETS", {})
    over = 512 * 1024 + 1
    # Saturate this client's window.
    for _ in range(web_app._RATE_LIMIT):
        client.post("/api/verify", content=b"{}", headers={"content-type": "application/json"})
    # The next request is over the size limit too; if size ran first it would be 413. Rate wins => 429.
    resp = client.post("/api/verify", content=b"x" * over, headers={"content-type": "application/json"})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "60"


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


def test_saturated_reconcile_returns_503_before_reading(monkeypatch):
    # A slot must be reserved BEFORE any file read/copy, so an over-capacity request is turned away
    # without ingesting ~45 MB or stalling the event loop (Qodo #36: admission before preprocessing).
    reconciled = []
    monkeypatch.setattr(web_app, "reconcile", lambda *a: reconciled.append(True) or {})
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name in ("b", "r", "l"):
            path = os.path.join(tmp, name)
            open(path, "wb").close()
            paths.append(path)
        web_app._RECONCILE_SEMAPHORE.acquire()
        web_app._RECONCILE_SEMAPHORE.acquire()
        try:
            with pytest.raises(HTTPException) as caught:
                asyncio.run(web_app._run_safely_async(tmp, *paths))
            assert caught.value.status_code == 503
            assert reconciled == []  # rejected before any read / reconcile ran
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


def test_cancellation_before_worker_starts_releases_slot(monkeypatch):
    # If the offload is cancelled before the worker thread runs, the handler must free the slot it
    # reserved — otherwise the slot leaks and later requests get a spurious 503 (Qodo #36).
    async def _cancel_before_worker(fn, *args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(web_app.asyncio, "to_thread", _cancel_before_worker)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name in ("b", "r", "l"):
            path = os.path.join(tmp, name)
            open(path, "wb").close()
            paths.append(path)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(web_app._run_safely_async(tmp, *paths))
    # The slot must be free again: acquire both slots without blocking, then restore.
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()
    web_app._RECONCILE_SEMAPHORE.release()


def test_worker_file_read_failure_is_sanitized(monkeypatch):
    # A missing input makes the worker's read fail; that must surface as a leak-free HTTPException
    # (mapped through _kind_error), not an unhandled exception carrying a server path (Qodo #36).
    with tempfile.TemporaryDirectory() as tmp:
        # Only recon and ledger exist; the bank path is missing so open() raises inside the worker.
        paths = [os.path.join(tmp, n) for n in ("b", "r", "l")]
        for p in paths[1:]:
            open(p, "wb").close()
        with pytest.raises(HTTPException) as caught:
            asyncio.run(web_app._run_safely_async(tmp, *paths))
        assert caught.value.status_code in (422, 500)
        assert tmp not in str(caught.value.detail)  # no server path leaked
    # slot restored after the sanitized failure
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()

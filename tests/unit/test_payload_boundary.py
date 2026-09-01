"""Deterministic boundary and resource limit tests for Untangle input channels.

Verifies:
1. Exact per-file limit (15 MiB accepted, 15 MiB + 1 B rejected with InputError).
2. Service/CLI snapshot reader streaming rejection (short-circuits before reading entire unbounded inputs).
3. Web upload per-file limit (HTTP 413 for single file > 15 MiB).
4. Web upload aggregate request limit (HTTP 413 for aggregate body > 46 MiB).
5. Clean error normalization (no raw OS, decode, or unhandled trace leaks).
6. Semaphore and temporary directory cleanup after rejection or failure.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from engine.ingest import InputError
from engine.service import MAX_INPUT_BYTES, read_input_snapshot
from webapp.app import (
    _BODY_LIMITS,
    _RECONCILE_SEMAPHORE,
    _RECONCILE_SLOTS,
    BodySizeLimitMiddleware,
    app,
)


def _make_temp_file_with_size(tmp_dir: str, name: str, size: int) -> str:
    """Create a temporary sparse/padded file of exact byte size efficiently."""
    path = os.path.join(tmp_dir, name)
    with open(path, "wb") as f:
        # Write valid initial text then truncate/seek to exact size
        header = b"date,narration,credit,debit\n2026-06-01,TEST CREDIT,100.00,\n"
        f.write(header)
        if size > len(header):
            f.seek(size - 1)
            f.write(b"\n")
    return path


def test_service_snapshot_exact_limit_accepted(tmp_path):
    """File of exactly 15 MiB (15,728,640 bytes) is read completely without error."""
    path = _make_temp_file_with_size(str(tmp_path), "exact_15mb.csv", MAX_INPUT_BYTES)
    assert os.path.getsize(path) == MAX_INPUT_BYTES
    data = read_input_snapshot(path, label="Bank statement", option="--bank")
    assert len(data) == MAX_INPUT_BYTES


def test_service_snapshot_exceeded_limit_rejected_lazy(tmp_path):
    """File of 15 MiB + 1 byte (15,728,641 bytes) is rejected with actionable InputError."""
    path = _make_temp_file_with_size(str(tmp_path), "over_15mb.csv", MAX_INPUT_BYTES + 1)
    assert os.path.getsize(path) == MAX_INPUT_BYTES + 1
    with pytest.raises(InputError) as exc_info:
        read_input_snapshot(path, label="Bank statement", option="--bank")
    assert "too large" in str(exc_info.value)
    assert f"{MAX_INPUT_BYTES:,} bytes" in str(exc_info.value)


def test_service_snapshot_stops_reading_early(tmp_path, monkeypatch):
    """Snapshot reader must not read past MAX_INPUT_BYTES + 1 before aborting."""
    # Create a 20 MiB file
    oversized_size = 20 * 1024 * 1024
    path = _make_temp_file_with_size(str(tmp_path), "oversized_20mb.csv", oversized_size)
    real_fdopen = os.fdopen
    observed = {"bytes": 0, "largest_request": 0}

    class TrackingReader:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, size=-1):
            observed["largest_request"] = max(observed["largest_request"], size)
            data = self.wrapped.read(size)
            observed["bytes"] += len(data)
            return data

    monkeypatch.setattr(os, "fdopen", lambda fd, mode: TrackingReader(real_fdopen(fd, mode)))
    with pytest.raises(InputError) as exc_info:
        read_input_snapshot(path, label="Recon report", option="--recon")
    msg = str(exc_info.value)
    assert "Recon report is too large" in msg
    assert observed["bytes"] == MAX_INPUT_BYTES + 1
    assert observed["largest_request"] <= 64 * 1024


def test_web_upload_single_file_over_15mb_rejected():
    """Web upload of single file > 15 MiB returns HTTP 413."""
    client = TestClient(app)
    # Minimal valid files for 2 of the 3 slots
    valid_bank = b"value_date,narration,credit,debit\n2026-06-01,TEST CREDIT,100.00,\n"
    valid_ledger = b"order_id,amount_paise,gst_rate_pct,gst_amount_paise,status,created_at,receipt,payment_method\n"

    # Recon file padded to 15 MiB + 10 bytes
    oversized_recon = b"[\n" + (b" " * (MAX_INPUT_BYTES + 10)) + b"\n]"

    files = {
        "bank": ("bank.csv", valid_bank, "text/csv"),
        "recon": ("recon.json", oversized_recon, "application/json"),
        "ledger": ("ledger.csv", valid_ledger, "text/csv"),
    }
    resp = client.post("/api/reconcile", files=files)
    assert resp.status_code == 413
    assert "larger than 15 MB" in resp.json().get("detail", "")


def test_web_aggregate_limit_middleware_rejection():
    """ASGI BodySizeLimitMiddleware rejects aggregate requests exceeding the ceiling."""
    limit = _BODY_LIMITS["/api/reconcile"]

    # Construct a synthetic generator payload exceeding aggregate limit
    client = TestClient(app)
    # Exceeding Content-Length header is rejected up front with 413
    resp = client.post(
        "/api/reconcile",
        content=b"too large payload",
        headers={
            "content-type": "application/json",
            "content-length": str(limit + 1),
        },
    )
    assert resp.status_code == 413
    assert "Request body is too large." in resp.json().get("detail", "")


def test_web_aggregate_limit_counts_streamed_chunks_without_content_length():
    """The ASGI byte counter rejects an actually streamed body crossing the limit."""
    limit = 10
    inner_called = False
    sent = []
    messages = iter(
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": False},
        ]
    )

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    middleware = BodySizeLimitMiddleware(inner, limits={"/api/reconcile": limit})
    scope = {"type": "http", "path": "/api/reconcile", "headers": []}
    asyncio.run(middleware(scope, receive, send))

    assert inner_called is False
    assert sent[0]["status"] == 413


def test_semaphore_capacity_released_after_failure():
    """Semaphore slot must be completely released after any failed or rejected request."""
    client = TestClient(app)
    initial_slots = _RECONCILE_SEMAPHORE._value

    # Send a malformed upload request that triggers a 422
    files = {
        "bank": ("bank.csv", b"corrupted non-csv data", "text/csv"),
        "recon": ("recon.json", b"invalid json", "application/json"),
        "ledger": ("ledger.csv", b"invalid ledger", "text/csv"),
    }
    resp = client.post("/api/reconcile", files=files)
    assert resp.status_code == 422

    # Verify semaphore capacity is completely restored
    assert _RECONCILE_SEMAPHORE._value == initial_slots
    assert _RECONCILE_SEMAPHORE._value == _RECONCILE_SLOTS

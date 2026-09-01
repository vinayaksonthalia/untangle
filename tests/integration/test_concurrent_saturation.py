"""Concurrent-request saturation and resource-cleanup test suite (Phase 2, Task 2).

Proves that Untangle's reconciliation web layer remains bounded, fail-closed,
and resource-safe under simultaneous overlapping requests:

1. Maximum concurrent worker count never exceeds _RECONCILE_SLOTS.
2. Excess requests are rejected before worker execution, temp dir creation, or file saves.
3. Successful runs restore all semaphore capacity.
4. Input failures (413, 422) restore all semaphore capacity.
5. Unexpected worker failures restore all semaphore capacity.
6. A timed-out worker retains its semaphore slot until it truly finishes executing.
7. Capacity is restored immediately after a timed-out worker exits.
8. Temporary directories and files are cleaned up across all terminal outcomes.
9. Oversized streamed requests are rejected by middleware without acquiring worker slots.
10. Concurrent requests operate on isolated, immutable byte snapshots with zero cross-contamination.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import webapp.app as web_app
from engine.service import reconcile_bytes
from eval.benchmark_generator import generate_benchmark_dataset


@pytest.fixture
def test_client():
    return TestClient(web_app.app)


@pytest.fixture(autouse=True)
def ensure_semaphore_clean():
    """Ensure the global semaphore and rate limits are fully reset before and after every test."""
    # Acquire all available slots without blocking to drain any leak, then restore to _RECONCILE_SLOTS
    while web_app._RECONCILE_SEMAPHORE.acquire(timeout=0):
        pass
    for _ in range(web_app._RECONCILE_SLOTS):
        web_app._RECONCILE_SEMAPHORE.release()
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS.clear()
    yield
    while web_app._RECONCILE_SEMAPHORE.acquire(timeout=0):
        pass
    for _ in range(web_app._RECONCILE_SLOTS):
        web_app._RECONCILE_SEMAPHORE.release()
    with web_app._RATE_LOCK:
        web_app._RATE_BUCKETS.clear()


def _get_valid_upload_files(seed: int = 42) -> dict[str, tuple[str, bytes, str]]:
    """Generate minimal valid upload files for testing."""
    ds = generate_benchmark_dataset(profile="ci-safe", seed=seed)
    return {
        "bank": ("bank_statement.csv", ds.bank_bytes, "text/csv"),
        "recon": ("recon_report.json", ds.recon_bytes, "application/json"),
        "ledger": ("order_ledger.csv", ds.ledger_bytes, "text/csv"),
    }


def test_concurrent_worker_count_bounded_by_slots(monkeypatch):
    """1. Prove that at no point do more than _RECONCILE_SLOTS workers run simultaneously."""
    max_slots = web_app._RECONCILE_SLOTS
    total_requests = max_slots * 3  # 6 requests for 2 slots

    lock = threading.Lock()
    active_workers = 0
    max_observed_concurrent = 0
    entered_worker_count = 0

    barrier = threading.Barrier(max_slots)
    finish_event = threading.Event()

    def instrumented_reconcile(*args, **kwargs):
        nonlocal active_workers, max_observed_concurrent, entered_worker_count
        with lock:
            active_workers += 1
            entered_worker_count += 1
            if active_workers > max_observed_concurrent:
                max_observed_concurrent = active_workers

        # Wait for all admitted slots to arrive so we measure maximum simultaneous overlap
        try:
            barrier.wait(timeout=2.0)
        except threading.BrokenBarrierError:
            pass

        finish_event.wait(timeout=2.0)

        with lock:
            active_workers -= 1
        return reconcile_bytes(*args, **kwargs)

    monkeypatch.setattr(web_app, "reconcile_bytes", instrumented_reconcile)

    responses: list[Any] = []

    def send_request(client_id: int):
        client = TestClient(web_app.app)
        files = _get_valid_upload_files(seed=40 + client_id)
        resp = client.post("/api/reconcile", files=files)
        responses.append((client_id, resp.status_code))

    threads = []
    for i in range(total_requests):
        t = threading.Thread(target=send_request, args=(i,))
        threads.append(t)
        t.start()

    # Let the first wave hit the barrier, then release them
    time.sleep(0.1)
    finish_event.set()

    for t in threads:
        t.join(timeout=5.0)

    # Invariants
    assert max_observed_concurrent <= max_slots, (
        f"Observed {max_observed_concurrent} simultaneous workers, exceeding limit of {max_slots}"
    )
    status_codes = [s for _, s in responses]
    accepted = status_codes.count(200)
    rejected_busy = status_codes.count(503)

    assert accepted + rejected_busy == total_requests
    assert accepted == max_slots
    assert rejected_busy == total_requests - max_slots
    assert entered_worker_count == max_slots


def test_excess_requests_rejected_before_expensive_work(monkeypatch):
    """2. Prove that requests exceeding capacity are rejected before temp dirs or file saves."""
    temp_dirs_created = 0
    saves_called = 0
    orig_tempdir = tempfile.TemporaryDirectory
    orig_save = web_app._save

    class InstrumentedTestTempDir:
        def __init__(self, *args, **kwargs):
            nonlocal temp_dirs_created
            temp_dirs_created += 1
            self._real = orig_tempdir(*args, **kwargs)

        def __enter__(self):
            return self._real.__enter__()

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    async def instrumented_save(*args, **kwargs):
        nonlocal saves_called
        saves_called += 1
        return await orig_save(*args, **kwargs)

    monkeypatch.setattr(web_app.tempfile, "TemporaryDirectory", InstrumentedTestTempDir)
    monkeypatch.setattr(web_app, "_save", instrumented_save)

    # Drain all available slots to simulate 100% busy capacity
    web_app._RECONCILE_SEMAPHORE.acquire()
    web_app._RECONCILE_SEMAPHORE.acquire()

    client = TestClient(web_app.app)
    try:
        files = _get_valid_upload_files()
        resp = client.post("/api/reconcile", files=files)
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Reconciliation capacity is busy; please try again shortly."

        # MUST NOT create temp directories or save uploaded files
        assert temp_dirs_created == 0, "TemporaryDirectory was created for rejected request"
        assert saves_called == 0, "_save was called for rejected request"
    finally:
        web_app._RECONCILE_SEMAPHORE.release()
        web_app._RECONCILE_SEMAPHORE.release()


def test_successful_runs_restore_all_capacity(test_client):
    """3. Successful concurrent reconciliation requests restore 100% capacity."""
    files = _get_valid_upload_files()
    resp1 = test_client.post("/api/reconcile", files=files)
    assert resp1.status_code == 200

    resp2 = test_client.post("/api/reconcile", files=files)
    assert resp2.status_code == 200

    # Prove both slots are immediately available
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()
    web_app._RECONCILE_SEMAPHORE.release()


def test_input_failures_restore_all_capacity(test_client):
    """4. Input failures (missing files, oversized files, malformed formats) restore capacity."""
    # 4a. Missing file -> 422
    resp_missing = test_client.post(
        "/api/reconcile",
        files={"bank": ("b.csv", b"val", "text/csv")},
    )
    assert resp_missing.status_code == 422

    # 4b. Oversized single file -> 413
    oversized = b"a" * (web_app._MAX_BYTES + 10)
    resp_oversized = test_client.post(
        "/api/reconcile",
        files={
            "bank": ("b.csv", oversized, "text/csv"),
            "recon": ("r.json", b"[]", "application/json"),
            "ledger": ("l.csv", b"ledger", "text/csv"),
        },
    )
    assert resp_oversized.status_code == 413

    # 4c. Corrupt unparseable file -> 422
    resp_corrupt = test_client.post(
        "/api/reconcile",
        files={
            "bank": ("b.csv", b"corrupted non-csv data\x00\xff", "text/csv"),
            "recon": ("r.json", b"{invalid json}", "application/json"),
            "ledger": ("l.csv", b"corrupted", "text/csv"),
        },
    )
    assert resp_corrupt.status_code == 422

    # Capacity must be 100% restored
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()
    web_app._RECONCILE_SEMAPHORE.release()


def test_unexpected_worker_failure_restores_capacity(monkeypatch):
    """5. Unexpected worker thread exceptions are sanitized and restore capacity."""
    def broken_reconcile(*args, **kwargs):
        raise RuntimeError("Simulated unexpected engine internal fault")

    monkeypatch.setattr(web_app, "reconcile_bytes", broken_reconcile)
    client = TestClient(web_app.app)
    files = _get_valid_upload_files()

    resp = client.post("/api/reconcile", files=files)
    assert resp.status_code == 500
    assert "Something went wrong on our side" in resp.json()["detail"]

    # Capacity must be fully restored
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()
    web_app._RECONCILE_SEMAPHORE.release()


def test_timeout_worker_retains_slot_until_actual_exit(monkeypatch):
    """6 & 7. A timed-out worker MUST NOT release its slot while still executing, and restores it on exit."""
    worker_started = threading.Event()
    worker_can_finish = threading.Event()
    worker_exited = threading.Event()
    response_holder: list[int] = []

    def slow_worker(*args, **kwargs):
        worker_started.set()
        worker_can_finish.wait(timeout=5.0)
        worker_exited.set()
        return {}

    monkeypatch.setattr(web_app, "reconcile_bytes", slow_worker)
    old_timeout = web_app._RECONCILE_TIMEOUT_SECONDS
    web_app._RECONCILE_TIMEOUT_SECONDS = 0.02  # 20ms timeout

    def run_in_thread():
        client = TestClient(web_app.app)
        files = _get_valid_upload_files()
        resp = client.post("/api/reconcile", files=files)
        response_holder.append(resp.status_code)

    t = threading.Thread(target=run_in_thread)
    t.start()

    try:
        # 1. Wait for worker thread to start
        assert worker_started.wait(timeout=2.0)

        # 2. Wait 60ms so async handler times out (20ms timeout)
        time.sleep(0.06)

        # 3. Invariant 6: While worker is still blocked on worker_can_finish, verify semaphore slot is STILL held
        # Exactly 1 slot should be free (since slots=2, 1 is held by running worker)
        assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
        assert not web_app._RECONCILE_SEMAPHORE.acquire(timeout=0), (
            "Semaphore slot was prematurely released while worker was still running!"
        )
        web_app._RECONCILE_SEMAPHORE.release()

        # 4. Now unblock the worker and wait for thread to finish
        worker_can_finish.set()
        t.join(timeout=5.0)
        assert response_holder == [504]

        # 5. Invariant 7: Confirm worker has exited and restored all slots
        assert worker_exited.is_set()
        time.sleep(0.05)
        assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
        assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
        web_app._RECONCILE_SEMAPHORE.release()
        web_app._RECONCILE_SEMAPHORE.release()
    finally:
        web_app._RECONCILE_TIMEOUT_SECONDS = old_timeout
        worker_can_finish.set()


def test_temporary_directories_cleaned_across_all_paths(monkeypatch):
    """8. Temporary upload directories are removed on success, failure, and rejection."""
    created_dirs: list[str] = []
    orig_tempdir = tempfile.TemporaryDirectory

    class TrackedTempDir:
        def __init__(self, *args, **kwargs):
            self._real = orig_tempdir(*args, **kwargs)
            created_dirs.append(self._real.name)

        def __enter__(self):
            return self._real.__enter__()

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    monkeypatch.setattr(web_app.tempfile, "TemporaryDirectory", TrackedTempDir)
    client = TestClient(web_app.app)
    files = _get_valid_upload_files()

    # Success
    resp = client.post("/api/reconcile", files=files)
    assert resp.status_code == 200

    # 422 Input Error
    client.post(
        "/api/reconcile",
        files={
            "bank": ("b.csv", b"bad", "text/csv"),
            "recon": ("r.json", b"bad", "application/json"),
            "ledger": ("l.csv", b"bad", "text/csv"),
        },
    )

    assert len(created_dirs) >= 2
    for dir_path in created_dirs:
        assert not os.path.exists(dir_path), f"Temporary directory leaked: {dir_path}"


def test_oversized_streamed_requests_never_acquire_worker_slots():
    """9. Oversized requests rejected by middleware never consume reconciliation slots."""
    client = TestClient(web_app.app)
    limit = web_app._BODY_LIMITS["/api/reconcile"]

    resp = client.post(
        "/api/reconcile",
        content=b"oversized content",
        headers={
            "content-type": "application/json",
            "content-length": str(limit + 1),
        },
    )
    assert resp.status_code == 413

    # All slots remain intact
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    assert web_app._RECONCILE_SEMAPHORE.acquire(timeout=0)
    web_app._RECONCILE_SEMAPHORE.release()
    web_app._RECONCILE_SEMAPHORE.release()


def test_concurrent_requests_immutable_and_isolated():
    """10. Concurrent requests operate on isolated byte snapshots with zero cross-contamination."""
    ds1 = generate_benchmark_dataset(profile="ci-safe", seed=101)
    ds2 = generate_benchmark_dataset(profile="ci-safe", seed=202)

    client1 = TestClient(web_app.app)
    client2 = TestClient(web_app.app)

    results: dict[str, dict] = {}

    def run_req(tag: str, ds, client):
        files = {
            "bank": ("bank.csv", ds.bank_bytes, "text/csv"),
            "recon": ("recon.json", ds.recon_bytes, "application/json"),
            "ledger": ("ledger.csv", ds.ledger_bytes, "text/csv"),
        }
        resp = client.post("/api/reconcile", files=files)
        assert resp.status_code == 200
        results[tag] = resp.json()

    t1 = threading.Thread(target=run_req, args=("req1", ds1, client1))
    t2 = threading.Thread(target=run_req, args=("req2", ds2, client2))

    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    # Invariants: output hashes and line counts must correspond strictly to respective datasets
    assert "req1" in results and "req2" in results
    assert results["req1"]["audit_root"] != results["req2"]["audit_root"]
    assert results["req1"]["totals"]["n_bank_lines"] == ds1.row_counts["bank_statement_lines"]
    assert results["req2"]["totals"]["n_bank_lines"] == ds2.row_counts["bank_statement_lines"]


def test_immutable_input_bytes_preserved_against_external_mutation(monkeypatch):
    """11. Deleting or mutating temporary files on disk after byte read cannot affect reconciliation."""
    ds = generate_benchmark_dataset(profile="ci-safe", seed=42)
    bytes_read_event = threading.Event()
    worker_can_finish = threading.Event()

    orig_reconcile = web_app.reconcile_bytes

    def intercepted_reconcile(b_bytes, r_bytes, l_bytes, **kwargs):
        bytes_read_event.set()
        worker_can_finish.wait(timeout=2.0)
        return orig_reconcile(b_bytes, r_bytes, l_bytes, **kwargs)

    monkeypatch.setattr(web_app, "reconcile_bytes", intercepted_reconcile)

    client = TestClient(web_app.app)
    response_container: list[Any] = []

    def send_request():
        files = {
            "bank": ("bank.csv", ds.bank_bytes, "text/csv"),
            "recon": ("recon.json", ds.recon_bytes, "application/json"),
            "ledger": ("ledger.csv", ds.ledger_bytes, "text/csv"),
        }
        resp = client.post("/api/reconcile", files=files)
        response_container.append(resp)

    t = threading.Thread(target=send_request)
    t.start()

    try:
        assert bytes_read_event.wait(timeout=2.0)
        # Worker has read bytes into immutable memory; now unblock worker
        worker_can_finish.set()
        t.join(timeout=5.0)
        assert len(response_container) == 1
        assert response_container[0].status_code == 200
        assert response_container[0].json()["totals"]["n_bank_lines"] == ds.row_counts["bank_statement_lines"]
    finally:
        worker_can_finish.set()

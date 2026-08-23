"""Web app end-to-end + adversarial tests (the breaking pass, made permanent)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from webapp.app import app

DATA = "data"
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(DATA, "bank_statement.csv")),
    reason="generate data first",
)
client = TestClient(app, raise_server_exceptions=False)


def _files(**over):
    base = {
        "bank": ("b.csv", open(f"{DATA}/bank_statement.csv", "rb").read(), "text/csv"),
        "recon": ("r.json", open(f"{DATA}/recon_report.json", "rb").read(), "application/json"),
        "ledger": ("l.csv", open(f"{DATA}/order_ledger.csv", "rb").read(), "text/csv"),
    }
    base.update(over)
    return base


def test_pages_render():
    for path, marker in [("/", "pile of credits"), ("/app", "Drop your three files"),
                         ("/try-sample", "Exception queue")]:
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text, path


def test_api_reconcile_happy_path():
    r = client.post("/api/reconcile", files=_files())
    assert r.status_code == 200
    t = r.json()["totals"]
    assert t["reconciled_count"] > 0 and t["fee_gst_recoverable_paise"] > 0


def test_browser_reconcile_returns_dashboard():
    r = client.post("/reconcile", files=_files())
    assert r.status_code == 200 and "Exception queue" in r.text


@pytest.mark.parametrize("name,payload", [
    ("garbage_binary", b"\x00\xff\xfe not a csv \x9c" * 50),
    ("empty", b""),
    ("json_as_csv", b'[{"entity_id": "pay_x"}]'),
    ("pdf_renamed", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj"),
])
def test_hostile_bank_file_fails_kindly(name, payload):
    r = client.post("/api/reconcile", files=_files(bank=("x.csv", payload, "text/csv")))
    assert 400 <= r.status_code < 500, name
    assert "Traceback" not in r.text and "/var/folders" not in r.text and "untangle_" not in r.text


def test_oversize_rejected_413():
    r = client.post("/api/reconcile", files=_files(bank=("x.csv", b"a" * (16 * 1024 * 1024), "text/csv")))
    assert r.status_code == 413


def test_missing_file_422():
    files = _files(); files.pop("ledger")
    r = client.post("/api/reconcile", files=files)
    assert r.status_code == 422


def test_error_never_leaks_temp_path():
    r = client.post("/api/reconcile", files=_files(recon=("r.json", b"not json", "application/json")))
    assert 400 <= r.status_code < 500
    assert "/var/folders" not in r.text and "untangle_" not in r.text

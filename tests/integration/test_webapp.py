"""Web app end-to-end + adversarial tests (the breaking pass, made permanent)."""
from __future__ import annotations

import json
import os
import re

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
    for path, marker in [("/", "Close your Razorpay settlement books"), ("/app", "Upload your files"),
                         ("/dashboard", "Settlement close")]:
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text, path


def test_try_sample_loads_demo_run():
    r = client.get("/try-sample")
    assert r.status_code == 200 and "sessionStorage" in r.text
    assert "untangle_run" not in r.headers.get("set-cookie", "")
    assert "no-store" in r.headers.get("cache-control", "")
    literal = re.search(r"sessionStorage\.setItem\('untangle_results', (.*)\); location", r.text).group(1)
    bundle = json.loads(json.loads(literal))
    assert bundle["version"] == 1 and bundle["mode"] == "demo"
    assert bundle["certificate"]["content_sha256"]
    assert bundle["presentation"].get("summary")
    assert isinstance(bundle["investigations"]["cases"], list)


def test_legacy_current_endpoints_are_explicitly_removed():
    for path in ("/api/presentation/current", "/api/investigations/current", "/api/certificate/current", "/api/journal/current.tally.xml"):
        assert client.get(path, cookies={"untangle_run": "someone-elses-run"}).status_code == 410


def test_api_reconcile_happy_path():
    r = client.post("/api/reconcile", files=_files())
    assert r.status_code == 200
    t = r.json()["totals"]
    assert t["reconciled_count"] > 0 and t["fee_gst_recoverable_paise"] > 0


def test_browser_reconcile_redirects_to_your_run():
    r = client.post("/reconcile", files=_files())
    assert r.status_code == 200 and "no-store" in r.headers.get("cache-control", "")
    assert "set-cookie" not in r.headers


def test_browser_bundle_escapes_script_terminator():
    from webapp.app import _bundle_response
    hostile = {"version": 1, "mode": "your_run", "metadata": "</script><script>alert(1)</script>"}
    r = _bundle_response(hostile)
    body = r.body.decode()
    assert body.count("</script>") == 1  # only the bootstrap tag closes
    literal = re.search(r"sessionStorage\.setItem\('untangle_results', (.*)\); location", body).group(1)
    assert json.loads(json.loads(literal))["metadata"] == "</script><script>alert(1)</script>"


def test_large_completed_bundle_downloads_without_truncation():
    from webapp.app import _bundle_response
    bundle = {"version": 1, "mode": "your_run", "x": "a" * (4 * 1024 * 1024)}
    response = _bundle_response(bundle)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="untangle-results.json"'
    assert json.loads(response.body) == bundle


def test_static_landing_css_revalidates_without_losing_body():
    r = client.get("/static/landing.css")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.content


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
    files = _files()
    files.pop("ledger")
    r = client.post("/api/reconcile", files=files)
    assert r.status_code == 422


def test_error_never_leaks_temp_path():
    r = client.post("/api/reconcile", files=_files(recon=("r.json", b"not json", "application/json")))
    assert 400 <= r.status_code < 500
    assert "/var/folders" not in r.text and "untangle_" not in r.text

"""Close-certificate document: routing, CSP, empty-by-default, run-scoped JSON."""
from __future__ import annotations

import pytest
import threading
import time
from fastapi.testclient import TestClient

from webapp import app as app_module
from webapp.app import app
from webapp.pages import certificate_page


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_certificate_route_serves_template(client):
    r = client.get("/certificate")
    assert r.status_code == 200
    assert r.text == certificate_page()
    assert "<title>Close certificate" in r.text


def test_certificate_no_external_resources(client):
    html = client.get("/certificate").text
    assert "cdn.tailwindcss.com" not in html and "fonts.googleapis.com" not in html
    assert "material-symbols-outlined" not in html


def test_certificate_residual_rendering_distinguishes_unavailable_zero_and_nonzero():
    html = client.get("/certificate").text
    # Keep all three safety branches present: unavailable is not silently rendered as zero,
    # and only a proven zero receives the green status.
    assert "Number.isSafeInteger(s.unresolved_paise)" in html
    assert "residualAvailable ? inr(residual) : 'Unavailable'" in html
    assert "residualAvailable && residual === 0 ? 'green' : 'amber'" in html


def test_certificate_csp_unchanged(client):
    assert client.get("/certificate").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_certificate_json_is_run_scoped(client):
    # no run -> 404 (nothing to certify); after loading the sample -> a real hash-bound cert
    fresh = TestClient(app, raise_server_exceptions=False)
    assert fresh.get("/api/certificate/current").status_code == 404
    fresh.get("/try-sample")  # loads the sample as the active run (sets the cookie)
    cert = fresh.get("/api/certificate/current")
    assert cert.status_code == 200
    body = cert.json()
    assert len(body.get("content_sha256", "")) == 64  # real SHA-256 content hash


def test_certificate_is_honest_about_signature_and_scope(client):
    html = client.get("/certificate").text
    # the document must not claim Merkle/secp256k1/SAP or statutory guarantees
    for bad in ("Merkle", "secp256k1", "SAP", "SOC 2", "ISO 27001", "guaranteed"):
        assert bad not in html, bad
    assert "read-only toward money and never posts" in html
    assert "hash-bound" in html  # the honest unsigned state is representable


def test_certificate_initialization_is_per_run_and_cached(monkeypatch):
    calls = []
    started = threading.Event()

    def fake_issue(report):
        calls.append(report)
        started.set()
        time.sleep(0.01)
        return {"content_sha256": "x"}

    monkeypatch.setattr(app_module, "issue_certificate", fake_issue)
    run = {"report": {"id": 1}}
    results = []
    threads = [threading.Thread(target=lambda: results.append(app_module._run_certificate(run))) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=3)
    assert len(calls) == 1
    assert results == [{"content_sha256": "x"}, {"content_sha256": "x"}]
    assert app_module._run_certificate(run) is results[0]
    assert len(calls) == 1

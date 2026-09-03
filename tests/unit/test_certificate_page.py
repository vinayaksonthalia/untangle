"""Close-certificate document: routing, CSP, empty-by-default, run-scoped JSON."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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

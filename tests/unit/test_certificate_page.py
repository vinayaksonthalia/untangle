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


def test_certificate_residual_rendering_distinguishes_unavailable_zero_and_nonzero(client):
    html = client.get("/certificate").text
    # Keep all three safety branches present: unavailable is not silently rendered as zero,
    # and only a proven zero receives the green status.
    assert "amount(cert.unresolved_inr)" in html
    assert "cert.unresolved_inr === '₹0.00' ? 'green' : 'amber'" in html
    assert "'Unavailable'" in html
    assert "p.summary" not in html
    assert "checked.hash_matches !== true" in html


def test_certificate_csp_unchanged(client):
    assert client.get("/certificate").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_certificate_is_honest_about_signature_and_scope(client):
    html = client.get("/certificate").text
    # the document must not claim Merkle/secp256k1/SAP or statutory guarantees
    for bad in ("Merkle", "secp256k1", "SAP", "SOC 2", "ISO 27001", "guaranteed"):
        assert bad not in html, bad
    assert "read-only toward money and never posts" in html
    assert "hash-bound" in html  # the honest unsigned state is representable

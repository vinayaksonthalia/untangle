"""Verify page: routing, self-hosted assets, CSP, honest wiring to /api/verify.

The Stitch design shipped a *fake* verifier (hardcoded id, always "VERIFIED" via
setTimeout). These tests pin that the served page instead reaches the real endpoint
and shows honest, nuanced verdicts — including failure on a tampered certificate.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app
from webapp.pages import verify_page


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_verify_route_serves_prebuilt_template(client):
    r = client.get("/verify")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text == verify_page()
    assert "<title>Verify a close certificate" in r.text


def test_verify_uses_only_local_assets(client):
    html = client.get("/verify").text
    assert '<link rel="stylesheet" href="/static/verify.css"/>' in html
    assert "material-symbols-outlined" not in html
    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', html):
        assert url.startswith("https://github.com/vinayaksonthalia/untangle"), url


def test_verify_icons_inline(client):
    html = client.get("/verify").text
    assert html.count('<svg viewBox="0 -960 960 960"') >= 15


def test_verify_css_served_with_fonts(client):
    r = client.get("/static/verify.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert r.text.count("@font-face") == 6


def test_csp_unchanged_on_verify(client):
    assert client.get("/verify").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_no_fabricated_verifier_strings(client):
    html = client.get("/verify").text
    # the design's faked/inaccurate labels must not survive
    for bad in (
        "CERT-9824",
        "Untangle Core Node",
        "Ledger Consensus",
        "Temporal Consistency",
        "Merkle Root",
        "PREMIUM ACCESS",
        "Integrity Level",
    ):
        assert bad not in html, bad
    # honest, accurate labels are present
    for good in (
        "Content hash (SHA-256)",
        "Content-hash integrity",
        "Proof-packet binding",
        "Verify certificate",
    ):
        assert good in html, good


def test_page_posts_to_real_verify_endpoint(client):
    html = client.get("/verify").text
    assert "/api/verify" in html  # the page wires to the real endpoint, not a simulation
    assert "setTimeout(() =>" not in html or "check-item" not in html  # no fake sequential theater


def test_real_verify_roundtrip_sample_and_tampered(client):
    cert = client.get("/api/certificate/sample").json()
    ok = client.post("/api/verify", content=json.dumps(cert)).json()
    assert ok["ok"] is True and ok["hash_matches"] is True

    tampered = json.loads(json.dumps(cert))
    tampered["certificate"]["_tamper"] = "x"
    bad = client.post("/api/verify", content=json.dumps(tampered)).json()
    assert bad["ok"] is False and bad["hash_matches"] is False


def test_nav_and_ctas_resolve(client):
    html = client.get("/verify").text
    for href in ('href="/app"', 'href="/try-sample"', 'href="/"'):
        assert href in html
    for path in ("/app", "/try-sample", "/"):
        assert client.get(path).status_code == 200

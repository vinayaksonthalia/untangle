"""Stitch dashboard: routing, self-hosted assets, CSP, live-data wiring, honest copy.

The dashboard is data-driven: it fetches the real /api/presentation payload and
populates every figure client-side. These tests pin that it ships no external
resources, keeps the CSP unchanged, wires to the real endpoint, and carries none
of the Stitch mock's fabricated numbers/persona.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app
from webapp.pages import dashboard_page


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_dashboard_route_serves_template(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text == dashboard_page()
    assert "<title>Reconciliation dashboard" in r.text


def test_dashboard_local_assets_only(client):
    html = client.get("/dashboard").text
    assert '<link rel="stylesheet" href="/static/dashboard.css"/>' in html
    assert "material-symbols-outlined" not in html
    assert "cdn.tailwindcss.com" not in html and "fonts.googleapis.com" not in html
    assert html.count('<svg viewBox="0 -960 960 960"') >= 6
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', html):
        assert url.startswith("https://github.com/vinayaksonthalia/untangle"), url


def test_dashboard_csp_unchanged(client):
    assert client.get("/dashboard").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_dashboard_wires_real_endpoint_not_mock_numbers(client):
    html = client.get("/dashboard").text
    assert "/api/presentation/sample" in html  # live data, not hardcoded
    # none of the Stitch mock's fabricated values/persona survive
    for bad in ("94.2%", "1,42,850.50", "12,430.20", "TRX-8919", "SET-4492",
                "Audit Officer", "PREMIUM ACCESS", "Integrity Level"):
        assert bad not in html, bad


def test_dashboard_css_and_data_endpoints(client):
    css = client.get("/static/dashboard.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert css.text.count("@font-face") == 6
    # the endpoint it depends on actually resolves and carries a summary
    pres = client.get("/api/presentation/sample")
    assert pres.status_code == 200
    assert "summary" in pres.json()


def test_dashboard_download_and_verify_links_resolve(client):
    html = client.get("/dashboard").text
    assert 'href="/api/journal/sample.tally.xml"' in html
    assert 'href="/verify"' in html
    assert client.get("/api/journal/sample.tally.xml").status_code == 200

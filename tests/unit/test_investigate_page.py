"""Investigate screen: routing, self-hosted assets, CSP, and real investigations wiring.

The page is client-rendered: it fetches /api/investigations/sample (the deterministic seed-42
investigation benchmark) and renders one case file at a time. These tests pin the route, the
CSP/asset discipline shared by every screen, and the real data contract behind it.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app
from webapp.pages import investigate_page


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_investigate_route_serves_template(client):
    r = client.get("/investigate")
    assert r.status_code == 200
    assert r.text == investigate_page()
    assert "<title>Investigate" in r.text


def test_investigate_local_assets_only(client):
    html = client.get("/investigate").text
    assert '<link rel="stylesheet" href="/static/investigate.css"/>' in html
    assert "material-symbols-outlined" not in html
    assert "cdn.tailwindcss.com" not in html and "fonts.googleapis.com" not in html
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', html):
        assert url.startswith("https://github.com/vinayaksonthalia/untangle"), url


def test_investigate_csp_unchanged(client):
    assert client.get("/investigate").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_investigate_css_served(client):
    r = client.get("/static/investigate.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert r.text.count("@font-face") == 6


def test_investigate_is_xss_safe(client):
    html = client.get("/investigate").text
    # dynamic strings must go through textContent / createTextNode, never innerHTML
    assert "innerHTML" not in html


def test_investigations_api_returns_benchmark(client):
    payload = client.get("/api/investigations/sample").json()
    s = payload["summary"]
    # the seed-42 benchmark: one settlement per root cause + one honest abstention
    assert s["total"] == 7 and s["resolved"] == 6 and s["abstained"] == 1
    causes = {c["root_cause"] for c in payload["cases"]}
    assert "unexplained" in causes
    assert {"mdr_fee_drift", "partial_capture", "rolling_reserve"} <= causes


def test_investigations_api_cases_are_well_formed(client):
    cases = client.get("/api/investigations/sample").json()["cases"]
    for c in cases:
        assert isinstance(c["candidates_tried"], list)
        assert isinstance(c["reasoning_trace"], list)
        if c["resolved"]:
            # a resolved case carries a matched candidate and a balanced corrective voucher
            assert any(x["matched"] for x in c["candidates_tried"])
            ce = c["corrective_entry"]
            assert ce and ce["balanced"] is True and ce["lines"]
        else:
            # the abstention must NOT fabricate a corrective entry
            assert c["root_cause"] == "unexplained"
            assert not c["corrective_entry"]

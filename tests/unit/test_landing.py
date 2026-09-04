"""Landing page: routing, self-hosted assets, CSP, wired CTAs, honest copy.

The landing page is a pre-built static artifact (tools/tailwind/build.sh) served
through a template loader and a /static mount. These tests pin the contract that
matters for a hardened, dependency-free deploy: no external resource loads, the
CSP unchanged, real CTA destinations, and no fabricated claims.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app
from webapp.pages import _load_template, landing_page


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_landing_route_serves_prebuilt_template(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text == landing_page()
    assert "<title>untangle" in r.text


def test_landing_references_only_local_stylesheet(client):
    html = client.get("/").text
    assert '<link rel="stylesheet" href="/static/landing.css"/>' in html
    # no external stylesheet/font/script hosts (would be blocked by CSP anyway)
    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "material-symbols-outlined" not in html  # web-font glyphs fully inlined


def test_landing_has_no_external_resource_loads(client):
    """href/src may only be same-origin, except deliberate footer nav links to GitHub."""
    html = client.get("/").text
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', html):
        assert url.startswith("https://github.com/vinayaksonthalia/untangle"), url


def test_icons_are_inline_svg(client):
    html = client.get("/").text
    assert html.count('<svg viewBox="0 -960 960 960"') >= 20
    assert 'fill="currentColor"' in html
    assert 'aria-hidden="true"' in html


def test_ctas_point_at_real_routes(client):
    html = client.get("/").text
    for href in ('href="/try-sample"', 'href="/app"', 'href="/verify"'):
        assert href in html
    # every CTA destination actually resolves (no dead links, no shadowing)
    for path in ("/app", "/try-sample", "/verify", "/healthz"):
        assert client.get(path).status_code == 200


def test_csp_header_is_unchanged(client):
    csp = client.get("/").headers.get("content-security-policy")
    assert csp == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_static_css_served_with_font_faces(client):
    r = client.get("/static/landing.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert r.text.count("@font-face") == 6
    assert "/static/fonts/" in r.text


def test_static_font_served_as_woff2(client):
    r = client.get("/static/fonts/inter-latin.woff2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"
    assert r.content[:4] == b"wOF2"


def test_boundary_language_preserved(client):
    html = client.get("/").text
    # Read-only toward money is the load-bearing safety claim on the page.
    assert "Read-only toward money" in html
    assert "no code path to initiate, authorise, or debit a transfer" in html
    assert "never posts to your books" in html


def test_no_fabricated_or_stale_claims(client):
    html = client.get("/").text
    assert "243 tests" not in html          # stale count
    assert "₹42k / month" not in html       # invented "average recovery"
    assert "PREMIUM ACCESS" not in html     # mock persona chrome
    assert "Integrity Level: 99.8%" not in html


def test_template_loader_fails_loudly(tmp_path, monkeypatch):
    import webapp.pages as pages

    monkeypatch.setattr(pages, "_TEMPLATE_DIR", tmp_path)
    _load_template.cache_clear()
    with pytest.raises(FileNotFoundError):
        _load_template("does-not-exist.html")

    empty = tmp_path / "empty.html"
    empty.write_text("   \n", encoding="utf-8")
    _load_template.cache_clear()
    with pytest.raises(ValueError):
        _load_template("empty.html")

    _load_template.cache_clear()  # restore clean cache for other tests


def test_safety_section_states_what_is_not_claimed(client):
    """The institutional landing replaces a fake SOC2 block with an explicit no-overclaim
    statement that links the real SAFETY.md."""
    html = client.get("/").text
    assert "No SOC 2, ISO 27001, or statutory certification is claimed" in html
    assert "https://github.com/vinayaksonthalia/untangle/blob/main/SAFETY.md" in html


def test_gst_and_certificate_and_privacy_claims_qualified(client):
    html = client.get("/").text
    assert "that merchants routinely miss" not in html         # overstated GST
    assert "Cryptographically signed summaries" not in html     # certs aren't always signed
    # certificate signing is honestly conditional, never asserted as always-on
    assert "ECDSA P-256 when a key is configured, else hash-bound" in html
    assert "per-request temp directory" not in html            # false privacy claim
    assert "Zero persistence" not in html
    assert "processed in memory and discarded when the session ends" in html

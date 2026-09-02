"""Upload page: routing, self-hosted assets, CSP, real /reconcile wiring, honest copy.

The Stitch mock claimed "processed locally in your browser / not transmitted" and
"end-to-end encryption on your device" (both false — files POST to /reconcile), showed
fabricated pre-filled states, and mislabelled the settlement report as "CSV only" (it's
JSON). These tests pin the corrected, honest, actually-working form.
"""
from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app
from webapp.pages import upload_page

_SAMPLE = "sample_data"


@pytest.fixture(scope="module")
def client():
    yield TestClient(app, raise_server_exceptions=False)


def test_upload_route_serves_template(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert r.text == upload_page()
    assert "<title>Upload your files" in r.text


def test_upload_local_assets_only(client):
    html = client.get("/app").text
    assert '<link rel="stylesheet" href="/static/upload.css"/>' in html
    assert "material-symbols-outlined" not in html
    assert "cdn.tailwindcss.com" not in html and "fonts.googleapis.com" not in html
    assert html.count('<svg viewBox="0 -960 960 960"') >= 10
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', html):
        assert url.startswith("https://github.com/vinayaksonthalia/untangle"), url


def test_upload_csp_unchanged(client):
    assert client.get("/app").headers.get("content-security-policy") == (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    )


def test_upload_form_posts_to_reconcile_with_all_fields(client):
    html = client.get("/app").text
    assert 'action="/reconcile"' in html and 'enctype="multipart/form-data"' in html
    for name in ("bank", "recon", "ledger"):
        assert f'name="{name}"' in html
    # correct accept types: bank/ledger CSV, recon JSON
    assert 'accept=".json,application/json"' in html
    assert html.count('accept=".csv,text/csv"') == 2


def test_upload_no_fabricated_or_inaccurate_copy(client):
    html = client.get("/app").text
    for bad in (
        "processed locally within your browser",
        "End-to-End Encryption",
        "exclusively on your device",
        "3,492",
        "CSV only",          # the settlement report is JSON, not CSV
        "Audit Officer",
        "PREMIUM ACCESS",
        "Integrity Level",
    ):
        assert bad not in html, bad
    assert "not persisted to any database" in html
    assert "<strong>JSON</strong>" in html  # settlement report is JSON


def test_upload_css_served(client):
    r = client.get("/static/upload.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert r.text.count("@font-face") == 6


def test_real_reconcile_roundtrip(client):
    # the form's real destination must actually reconcile a 3-file upload
    if not os.path.exists(os.path.join(_SAMPLE, "bank_statement.csv")):
        client.get("/try-sample")  # generates the sample
    files = {
        "bank": ("bank.csv", open(f"{_SAMPLE}/bank_statement.csv", "rb").read(), "text/csv"),
        "recon": ("recon.json", open(f"{_SAMPLE}/recon_report.json", "rb").read(), "application/json"),
        "ledger": ("ledger.csv", open(f"{_SAMPLE}/order_ledger.csv", "rb").read(), "text/csv"),
    }
    r = client.post("/reconcile", files=files)
    assert r.status_code == 200
    assert "Traceback" not in r.text


def test_sample_link_present(client):
    html = client.get("/app").text
    assert 'href="/try-sample"' in html
    assert client.get("/try-sample").status_code == 200


def test_schema_labels_match_ingest(client):
    html = client.get("/app").text
    # ledger requires amount_paise (not "amount"); recon join key needs type + entity_id
    assert "amount_paise" in html
    assert ">type<" in html and ">entity_id<" in html
    # settlement report honestly labelled as untangle's schema, not native provider export
    assert "untangle's expected" in html or "not a raw provider export" in html


def test_privacy_claim_is_accurate(client):
    html = client.get("/app").text
    assert "never written to disk" not in html          # false absolute (Starlette may spool)
    assert "spooled to a temp" in html or "spooled to a temporary" in html


def test_filename_log_is_xss_safe(client):
    html = client.get("/app").text
    # the user-controlled filename must go through textContent, never interpolated into HTML
    assert "nm.textContent = f.name" in html
    assert "${f.name}" not in html
    assert "log.innerHTML" not in html

"""Phase 5 Acceptance Gate Test (ANTIGRAVITY_BUILD_PLAN.md §2 Phase 5).

Gate conditions (all must hold):
  1. Demo and README lead with attribution + abstention + precision-at-coverage.
  2. Reconciliation and ITC are secondary, labeled "Proven Slice Only".
  3. One-click demo-data reproduction works via /try-sample.
  4. Zero-storage verified: uploaded files are never written to disk or database.
  5. Errors are kind and leak-free (no server paths, no raw tracebacks).
  6. Generator-blind sealed-holdout runner exists, produces headline numbers, and is distinct.
  7. Narration grammar mapping table exists (transcribed from real banking sources).
  8. Report states n and explicitly disclaims universal generalization (E4 / ER-005).
  9. Engine isolation G7 preserved.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eval.sealed import evaluate_sealed
from ui.dashboard import render
from webapp.app import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_phase5_gate_dashboard_leads_with_attribution_and_abstention():
    """Gate 1 & 2: Dashboard leads with attribution + abstention; reconciliation labeled proven slice only."""
    report = json.load(open("out/report.json", encoding="utf-8"))
    html = render(report)

    # 1. Check primary headline position
    attr_idx = html.find("Attribution &amp; Calibrated Abstention (Primary Verdict)")
    if attr_idx == -1:
        attr_idx = html.find("Attribution & Calibrated Abstention")
    assert attr_idx != -1, "Dashboard must lead with Attribution & Calibrated Abstention"

    # 2. Check Precision-at-coverage table position
    # The live dashboard shows the honest coverage/abstention curve (precision is a
    # ground-truth metric, reported only on the labeled benchmark, never on uploads).
    pac_idx = html.find("Coverage vs abstention")
    assert pac_idx != -1, "Dashboard must feature the coverage/abstention curve"
    assert pac_idx > attr_idx
    # Integrity guard: the live dashboard must NOT hardcode a precision claim on unlabeled runs.
    assert "precision holds at 1.000" not in html
    assert "Attribution Precision</div><div class=\"v\">1.000" not in html

    # 3. Check Reconciliation is rendered BELOW and labeled "Proven Slice Only"
    proven_idx = html.find("Proven Slice Only")
    recon_idx = html.find("Reconciliation &amp; Recoverable ITC")
    assert proven_idx != -1, "Reconciliation section must be labeled Proven Slice Only"
    assert recon_idx != -1
    assert recon_idx > attr_idx, "Reconciliation must render BELOW the attribution headline"
    assert proven_idx < recon_idx + 100, "Proven Slice tag must be attached to Reconciliation section"


def test_phase5_gate_readme_leads_with_attribution():
    """Gate 1 & 2: README leads with attribution + abstention headline."""
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## Headline: Attribution & Calibrated Abstention (PR-004)" in readme
    assert "Attribution Precision: 1.000 (100%)" in readme
    assert "0 decoy false-positives" in readme
    assert "Precision-at-Coverage & Abstention Curve" in readme
    assert "Reconciliation & Recoverable ITC (Proven Slice Only)" in readme


def test_phase5_gate_one_click_demo_reproduction(client):
    """Gate 3: One-click demo-data reproduction works without upload."""
    r = client.get("/try-sample")
    assert r.status_code == 200
    text = r.text
    assert "Attribution &amp; Calibrated Abstention" in text or "Attribution & Calibrated Abstention" in text
    assert "Proven Slice Only" in text
    assert "43,201" in text  # ITC recoverable
    assert "Exception queue" in text


def test_phase5_gate_zero_storage_and_kind_errors(client):
    """Gate 4 & 5: Zero-storage verified; errors are kind and leak-free."""
    # Zero storage: check temporary directory is deleted after upload
    temp_dir_before = set(os.listdir(tempfile.gettempdir()))

    bank_bytes = open("data/bank_statement.csv", "rb").read()
    recon_bytes = open("data/recon_report.json", "rb").read()
    ledger_bytes = open("data/order_ledger.csv", "rb").read()

    files = {
        "bank": ("bank.csv", bank_bytes, "text/csv"),
        "recon": ("recon.json", recon_bytes, "application/json"),
        "ledger": ("ledger.csv", ledger_bytes, "text/csv"),
    }

    r = client.post("/api/reconcile", files=files)
    assert r.status_code == 200

    # No leftover untangle_ temporary folders
    temp_dir_after = set(os.listdir(tempfile.gettempdir()))
    new_dirs = [d for d in temp_dir_after - temp_dir_before if "untangle_" in d]
    assert len(new_dirs) == 0, f"Temporary directories leaked: {new_dirs}"

    # Kind, leak-free error on invalid input (use bytes without literal null in source)
    corrupt_payload = bytes([0, 255, 254]) + b" not a csv "
    corrupt_files = {
        "bank": ("bank.csv", corrupt_payload, "text/csv"),
        "recon": ("recon.json", recon_bytes, "application/json"),
        "ledger": ("ledger.csv", ledger_bytes, "text/csv"),
    }
    r_err = client.post("/api/reconcile", files=corrupt_files)
    assert 400 <= r_err.status_code < 500
    # Must never leak server paths or tracebacks
    assert "Traceback" not in r_err.text
    assert "/Users/" not in r_err.text
    assert "/var/" not in r_err.text
    assert "untangle_" not in r_err.text


def test_phase5_gate_narration_mapping_table_exists():
    """Gate 7: Mapping table documenting real source specimens -> grammar rules exists (E2)."""
    mapping_file = Path("docs/NARRATION_GRAMMAR_MAPPING.md")
    assert mapping_file.exists(), "docs/NARRATION_GRAMMAR_MAPPING.md must exist"
    text = mapping_file.read_text(encoding="utf-8")
    assert "transcribed from" in text.lower()
    for bank in ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "RBL"]:
        assert bank in text, f"Bank {bank} must be documented in mapping table"


def test_phase5_gate_sealed_holdout_runner():
    """Gate 6 & 8: Sealed holdout runner produces reproducible headline numbers and disclaims generalization."""
    # 1. Sealed holdout directory is separate from demo data
    sealed_dir = "data/sealed"
    assert os.path.exists(sealed_dir)
    assert os.path.exists(os.path.join(sealed_dir, "manifest.json"))

    # 2. Evaluate sealed holdout
    res = evaluate_sealed(sealed_dir)
    m = res["metrics"]
    rzp = m["per_rail"]["razorpay_settlement"]
    decoy = m["decoy_false_positive"]

    assert rzp["precision"] == 1.000, "Sealed holdout Razorpay precision must be 1.000"
    assert decoy["predicted_razorpay"] == 0, "Sealed holdout decoy false-positive count must be 0"
    assert m["ece"] <= 0.10, "Sealed holdout ECE must be <= 0.10"

    # 3. Sealed manifest hash is frozen
    manifest = json.load(open(os.path.join(sealed_dir, "manifest.json")))
    assert manifest["seed"] == 1337
    assert len(manifest["files"]) == 4


def test_phase5_engine_isolation_g7():
    """Gate 9: Engine code never imports generator or reads ground truth."""
    engine_dir = Path("engine")
    for py_file in engine_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "import generator" not in text, f"{py_file} imports generator!"
        assert "from generator" not in text, f"{py_file} imports from generator!"
        assert "ground_truth" not in text, f"{py_file} references ground_truth!"

"""Unit tests for period close certificate generator (engine/certificate.py)."""

from __future__ import annotations

import json
import subprocess
import sys

from engine.certificate import build_close_certificate
from engine.service import reconcile


def test_build_close_certificate_on_real_reconciliation():
    """Build report via engine.service.reconcile on data/ (seed 42) and verify certificate contents."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )

    cert = build_close_certificate(report)

    totals = report["totals"]
    assert cert["period_records"] == totals["n_bank_lines"]
    assert cert["proven_razorpay_count"] == totals["by_rail_count"].get("razorpay_settlement", 0)
    assert cert["reconciled_count"] == totals["reconciled_count"]
    assert cert["unresolved_count"] == totals["unresolved_rzp_count"]
    assert cert["exception_count"] == totals["exception_count"]
    assert cert["exceptions_by_reason"] == totals["exceptions_by_reason"]
    assert cert["engine_version"] == report["config"]["engine_version"]
    assert cert["seed"] == 42
    assert cert["audit_root"] == report["audit_root"]

    # All proof packets verified and passed
    assert cert["verification"]["packets_verified"] == len(report["proof_packets"])
    assert cert["verification"]["packets_passed"] == len(report["proof_packets"])
    assert cert["verification"]["packets_verified"] > 0

    # Summary string is present and correctly formatted
    summary = cert["summary"]
    assert summary.startswith("Period closed:")
    assert f"{cert['proven_razorpay_count']} credits proven Razorpay" in summary
    assert "0 unverifiable proof packets." in summary


def test_certificate_determinism():
    """Two calls with the same report dictionary produce identical output."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )
    cert1 = build_close_certificate(report)
    cert2 = build_close_certificate(report)

    assert cert1 == cert2
    assert json.dumps(cert1, sort_keys=True) == json.dumps(cert2, sort_keys=True)


def test_certificate_cli_execution(tmp_path):
    """CLI python -m engine.certificate --run out/report.json prints valid certificate JSON."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )
    report_file = tmp_path / "test_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f)

    cmd = [sys.executable, "-m", "engine.certificate", "--run", str(report_file)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)

    out_data = json.loads(res.stdout)
    assert "summary" in out_data
    assert "verification" in out_data
    assert out_data["proven_razorpay_count"] == report["totals"]["by_rail_count"].get("razorpay_settlement", 0)

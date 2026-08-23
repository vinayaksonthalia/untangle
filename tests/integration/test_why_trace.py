"""`why` returns a complete trace for a real line (spec US3)."""
from __future__ import annotations

import json
import os

import pytest

from engine.cli import main

DATA = "data"
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(DATA, "bank_statement.csv")),
    reason="generate data first",
)


def test_why_reports_verdict_and_trace(tmp_path, capsys):
    out = str(tmp_path)
    rc = main(["run", "--bank", f"{DATA}/bank_statement.csv", "--recon",
               f"{DATA}/recon_report.json", "--ledger", f"{DATA}/order_ledger.csv",
               "--out", out, "--no-ai", "--seed", "42"])
    assert rc == 0
    report = json.load(open(os.path.join(out, "report.json")))
    # pick a reconciled razorpay line if any, else the first line
    key = (report["reconciliations"][0]["line_key"] if report["reconciliations"]
           else report["attributions"][0]["line_key"])
    capsys.readouterr()
    rc = main(["why", key, "--out", out])
    assert rc == 0
    text = capsys.readouterr().out
    assert key in text and "rail" in text and "evidence" in text

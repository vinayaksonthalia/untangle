"""Proof Packet builder + CSV export (evidence receipts)."""
from __future__ import annotations

from datetime import date, datetime

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.feegst import fee_gst
from engine.ingest import load_bank, load_recon
from engine.models import BankCreditLine, ReconRow
from engine.proof import build_proof_packets, proof_packets_to_csv, _csv_field
from engine.reconcile import reconcile


def test_proof_packets_only_cover_proven_razorpay():
    lines = load_bank("data/bank_statement.csv")
    recon = load_recon("data/recon_report.json")
    idx = ReconIndex(recon)
    attrs = attribute_all(lines, idx, 0.55)
    res, _unres, _sidx = reconcile({l.key: l for l in lines}, attrs, recon)
    fg = fee_gst(res, recon)
    packets = build_proof_packets(lines, attrs, res, recon, fg)
    proven = {a.line_key for a in attrs if a.rail == "razorpay_settlement" and not a.abstained}
    assert {p["line_key"] for p in packets} == proven
    for p in packets:
        assert p["verdict"]["rail"] == "razorpay_settlement"
        assert "ties" in p["proof"] and "rejected_alternatives" in p["proof"]
    csv = proof_packets_to_csv(packets)
    assert csv.splitlines()[0].startswith("line_key,value_date")
    assert len(csv.splitlines()) == len(packets) + 1


def test_csv_field_neutralizes_formula_injection():
    # A narration that is a spreadsheet formula must be neutralized (leading quote) and quoted.
    assert _csv_field("=SUM(A1:A9)").startswith("'=") or _csv_field("=SUM(A1:A9)").startswith('"\'=')
    assert _csv_field("+1234").startswith("'+") or _csv_field("+1234").startswith('"\'+')
    assert _csv_field("@x").startswith("'@") or _csv_field("@x").startswith('"\'@')
    # An ordinary field is untouched.
    assert _csv_field("RAZORPAY SETTLEMENT") == "RAZORPAY SETTLEMENT"


def test_embed_json_escapes_script_breakout():
    """A narration containing </script> must not break out of the <script> embed (stored XSS)."""
    from ui.dashboard import _embed_json
    s = _embed_json([{"narration": "</script><script>alert(1)</script>"}])
    assert "</script>" not in s
    assert "\\u003c/script\\u003e" in s or "\\u003c" in s
    # still valid JSON when unescaped back
    import json
    assert json.loads(s.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))[0]["narration"]

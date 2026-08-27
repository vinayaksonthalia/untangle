"""Proof Packet builder + CSV export (evidence receipts)."""
from __future__ import annotations

from datetime import date, datetime

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.feegst import fee_gst
from engine.ingest import load_bank, load_recon
from engine.models import BankCreditLine, ReconRow
from engine.proof import _csv_field, build_proof_packets, proof_packets_to_csv
from engine.reconcile import reconcile


def test_proof_packets_only_cover_proven_razorpay():
    lines = load_bank("data/bank_statement.csv")
    recon = load_recon("data/recon_report.json")
    idx = ReconIndex(recon)
    attrs = attribute_all(lines, idx, 0.55)
    res, _unres, _sidx = reconcile({ln.key: ln for ln in lines}, attrs, recon)
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


def test_pending_gst_not_reported_as_zero():
    """Qodo #1: an unresolved proven credit (e.g. reconstructed split leg) has UNKNOWN recoverable
    GST, not ₹0.00 — the packet must say 'pending', never a false ₹0.00."""
    lines = load_bank("data/bank_statement.csv")
    recon = load_recon("data/recon_report.json")
    idx = ReconIndex(recon)
    attrs = attribute_all(lines, idx, 0.55)
    res, _u, _s = reconcile({ln.key: ln for ln in lines}, attrs, recon)
    fg = fee_gst(res, recon)
    packets = build_proof_packets(lines, attrs, res, recon, fg)
    unresolved = [p for p in packets if not p["reconciled"]]
    assert unresolved, "benchmark has reconstructed split legs (unresolved proven credits)"
    for p in unresolved:
        assert p["fee_gst_recoverable_inr"] == "pending"
        assert "₹0.00" not in p["fee_gst_recoverable_inr"]


def test_rejected_alternatives_is_accurate_when_a_keyword_is_present():
    """Qodo #2: a UTR-exact credit that ALSO carries a competing keyword must not claim 'no
    competing keyword was present' — the statement is derived from the line's actual signals."""
    idx = ReconIndex([
        ReconRow("pay_1", "payment", 100000, 0, 0, 0, 100000, "setl_1", "1780498800xp8vma",
                 datetime(2026, 6, 10), datetime(2026, 6, 9), False, None, None, "upi", None)
    ])
    line = BankCreditLine("k", date(2026, 6, 10), 100000, "NEFT 1780498800xp8vma PAYU RAZORPAY", "1780498800xp8vma", True)
    attrs = attribute_all([line], idx, 0.55)
    fg = fee_gst([], [])
    packets = build_proof_packets([line], attrs, [], [], fg)
    assert packets and "no distinctive competing rail keyword" not in packets[0]["proof"]["rejected_alternatives"].lower()
    assert "outrank" in packets[0]["proof"]["rejected_alternatives"].lower()

"""Property tests for the Agentic Exception-Investigation Loop (Feature 006).

Properties verified:
1. ADDITIVITY: Building a report with investigation attached produces byte-identical
   headline totals, attributions, reconciliations, fee-GST recovery, exceptions, and proof packets.
2. DETERMINISM: Identical inputs yield identical Investigation results.
3. BALANCED ENTRIES: Every non-None corrective entry draft strictly balances (Debits == Credits).
4. HONEST ABSTENTION: When unexplained, no corrective voucher is drafted and confidence is 0.0.
"""

from __future__ import annotations

from pathlib import Path

from engine.cli import build_config, build_report
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.investigate import build_investigations

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def test_investigate_additivity():
    """Verify that attaching investigations does not alter any existing report metrics."""
    bank_path = str(DATA_DIR / "bank_statement.csv")
    recon_path = str(DATA_DIR / "recon_report.json")

    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    index = ReconIndex(recon_rows)

    from engine.attribute import attribute_all
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=0.55, seed=42)
    attributions = attribute_all(lines, index, cfg.threshold)

    # Report WITH investigations (Feature 006 default)
    rep_with, _ = build_report(
        cfg, lines, recon_rows, index, attributions,
        with_recovery=True, with_investigation=True
    )
    dict_with = rep_with.to_dict()

    # Report WITHOUT investigations (pre-Feature 006 baseline)
    rep_without, _ = build_report(
        cfg, lines, recon_rows, index, attributions,
        with_recovery=True, with_investigation=False
    )
    dict_without = rep_without.to_dict()

    # Invariant: totals, attributions, reconciliations, fee_gst, exceptions, proof_packets byte-identical
    assert dict_with["totals"] == dict_without["totals"]
    assert dict_with["attributions"] == dict_without["attributions"]
    assert dict_with["reconciliations"] == dict_without["reconciliations"]
    assert dict_with["fee_gst"] == dict_without["fee_gst"]
    assert dict_with["exceptions"] == dict_without["exceptions"]
    assert dict_with["proof_packets"] == dict_without["proof_packets"]
    assert dict_with["recovery_plan"] == dict_without["recovery_plan"]

    # Only the additive investigations key is present in rep_with
    assert "investigations" in dict_with
    assert "investigations" not in dict_without


def test_investigate_determinism():
    """Verify that investigating the same data multiple times is 100% deterministic."""
    bank_path = str(DATA_DIR / "bank_statement.csv")
    recon_path = str(DATA_DIR / "recon_report.json")

    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    index = ReconIndex(recon_rows)
    from engine.attribute import attribute_all
    attributions = attribute_all(lines, index, 0.55)

    from engine.reconcile import reconcile as reconcile_core
    lines_by_key = {ln.key: ln for ln in lines}
    reconciliations, _u, _s = reconcile_core(lines_by_key, attributions, recon_rows)

    from engine.exceptions import build_exceptions
    unresolved_rzp = [
        a.line_key for a in attributions
        if a.rail == "razorpay_settlement" and not any(r.line_key == a.line_key and r.balanced for r in reconciliations)
    ]
    exceptions = build_exceptions(attributions, unresolved_rzp, lines_by_key)

    invs1 = build_investigations(lines, attributions, reconciliations, recon_rows, index, exceptions)
    invs2 = build_investigations(lines, attributions, reconciliations, recon_rows, index, exceptions)

    assert len(invs1) == len(invs2)
    for i1, i2 in zip(invs1, invs2, strict=True):
        assert i1.to_dict() == i2.to_dict()


def test_investigate_all_emitted_entries_balance():
    """Verify that every single corrective double-entry voucher emitted strictly balances."""
    bank_path = str(DATA_DIR / "bank_statement.csv")
    recon_path = str(DATA_DIR / "recon_report.json")

    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    index = ReconIndex(recon_rows)
    from engine.attribute import attribute_all
    attributions = attribute_all(lines, index, 0.55)

    from engine.reconcile import reconcile as reconcile_core
    lines_by_key = {ln.key: ln for ln in lines}
    reconciliations, _u, _s = reconcile_core(lines_by_key, attributions, recon_rows)

    from engine.exceptions import build_exceptions
    unresolved_rzp = [
        a.line_key for a in attributions
        if a.rail == "razorpay_settlement" and not any(r.line_key == a.line_key and r.balanced for r in reconciliations)
    ]
    exceptions = build_exceptions(attributions, unresolved_rzp, lines_by_key)

    invs = build_investigations(lines, attributions, reconciliations, recon_rows, index, exceptions)

    for inv in invs:
        if inv.corrective_entry is not None:
            entry = inv.corrective_entry
            assert entry.get("balanced") is True
            lines = entry.get("lines", [])
            assert len(lines) >= 2
            total_debit = sum(
                round(float(ln["debit_inr"].replace("₹", "").replace(",", "").strip()) * 100)
                for ln in lines
            )
            total_credit = sum(
                round(float(ln["credit_inr"].replace("₹", "").replace(",", "").strip()) * 100)
                for ln in lines
            )
            assert total_debit == total_credit, f"Debits ({total_debit}) != Credits ({total_credit}) in {entry}"
        else:
            # A None corrective_entry means either the agent abstained (no root-cause class closed
            # the delta) or the credit already balanced exactly — both are valid no-entry outcomes.
            assert inv.root_cause in ("unexplained", "balanced")
            if inv.root_cause == "unexplained":
                assert inv.confidence == 0.0

"""Journal-entry export (engine/journal.py) — balanced double-entry + Tally XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.journal import build_journal_entries, to_journal_json, to_tally_xml
from engine.models import ReconciliationResult, ReconRow
from engine.reconcile import reconcile


def _row(eid, amount, fee, tax, sid="setl_1", utr="UTR1"):
    return ReconRow(
        entity_id=eid, type="payment", amount_paise=amount, fee_paise=fee, tax_paise=tax,
        debit_paise=0, credit_paise=amount - fee, settlement_id=sid, settlement_utr=utr,
        settled_at=datetime(2026, 6, 10), created_at=datetime(2026, 6, 10),
        on_hold=False, dispute_id=None, order_id=None, method="upi", description=None,
    )


def _recon(covered, credit_paise, sid="setl_1"):
    return ReconciliationResult(
        line_key="k1", covered_entity_ids=[("payment", e) for e in covered],
        covered_net_paise=credit_paise, credit_amount_paise=credit_paise,
        residual_paise=0, balanced=True,
    )


def test_every_entry_balances_and_gst_not_double_counted():
    # fee_paise=1000 INCLUDES tax_paise=180 (GST-on-fee). So MDR expense must be 820, ITC 180, net 9000.
    rows = [_row("pay_1", amount=10000, fee=1000, tax=180)]
    rec = _recon(["pay_1"], credit_paise=9000)
    entries = build_journal_entries([rec], rows, intra_state=True)
    assert len(entries) == 1
    e = entries[0]
    assert e.balanced
    led = {ln.ledger: (ln.debit_paise, ln.credit_paise) for ln in e.lines}
    assert led["Bank Current A/c"] == (9000, 0)
    assert led["Payment Gateway Charges"] == (820, 0)          # fee(1000) − tax(180), NOT 1000
    assert led["Input CGST"][0] + led["Input SGST"][0] == 180  # ITC = tax, split
    assert led["Razorpay Clearing A/c"] == (0, 9000 + 1000)    # clearing relieved = net + total fee
    assert e.total_debit_paise == e.total_credit_paise


def test_residual_posts_an_explicit_rounding_line():
    """Qodo #13: an accepted ±₹1 residual (bank credit ≠ covered settlement net) appears as an explicit
    Bank Charges & Rounding line and gross is derived from the settlement net — not hidden in Clearing."""
    rows = [_row("pay_1", amount=1000000, fee=1000, tax=180)]  # fee incl GST → MDR 820, ITC 180
    rec = ReconciliationResult(
        line_key="k1", covered_entity_ids=[("payment", "pay_1")],
        covered_net_paise=999000, credit_amount_paise=999005, residual_paise=5, balanced=True,
    )
    e = build_journal_entries([rec], rows, intra_state=True)[0]
    led = {ln.ledger: (ln.debit_paise, ln.credit_paise) for ln in e.lines}
    assert led["Bank Current A/c"] == (999005, 0)               # actual bank credit
    assert led["Bank Charges & Rounding"] == (0, 5)             # +5p residual booked explicitly (credit)
    assert led["Razorpay Clearing A/c"] == (0, 999000 + 1000)   # gross from SETTLEMENT net + total fee
    assert e.balanced


def test_real_razorpay_convention_tax_separate_from_fee():
    """A REAL Razorpay report keeps fee (ex-GST) and tax separate: credit = amount − fee − tax. The
    export must detect this and set MDR = fee (NOT fee − tax) so real uploads reconcile correctly."""
    # amount 10000, fee 200 (ex-GST), tax 36 → credit 9764 (real Razorpay sample row).
    row = ReconRow(
        entity_id="pay_r", type="payment", amount_paise=1000000, fee_paise=20000, tax_paise=3600,
        debit_paise=0, credit_paise=976400, settlement_id="setl_1", settlement_utr="U1",
        settled_at=datetime(2026, 6, 10), created_at=datetime(2026, 6, 10),
        on_hold=False, dispute_id=None, order_id=None, method="card", description=None,
    )
    e = build_journal_entries([_recon(["pay_r"], credit_paise=976400)], [row], intra_state=True)[0]
    led = {ln.ledger: ln.debit_paise for ln in e.lines if ln.debit_paise}
    assert led["Payment Gateway Charges"] == 20000            # fee is already ex-GST → not fee − tax
    assert led["Input CGST"] + led["Input SGST"] == 3600      # ITC = tax
    assert e.balanced


def test_inter_state_uses_single_igst_line():
    rows = [_row("pay_1", amount=10000, fee=1000, tax=180)]
    rec = _recon(["pay_1"], credit_paise=9000)
    e = build_journal_entries([rec], rows, intra_state=False)[0]
    led = {ln.ledger: ln.debit_paise for ln in e.lines}
    assert led.get("Input IGST") == 180
    assert "Input CGST" not in led and "Input SGST" not in led
    assert e.balanced


def test_tally_xml_sign_convention_and_balance():
    rows = [_row("pay_1", amount=10000, fee=1000, tax=180)]
    e = build_journal_entries([_recon(["pay_1"], 9000)], rows)
    xml = to_tally_xml(e, company="Acme & Co Pvt Ltd")  # '&' must be escaped
    root = ET.fromstring(xml)  # raises if not well-formed
    assert root.tag == "ENVELOPE"
    for v in root.iter("VOUCHER"):
        amts = [float(a.text) for a in v.iter("AMOUNT")]
        assert abs(sum(amts)) < 0.005, "each voucher's AMOUNT tags must sum to zero"
        for le in v.iter("ALLLEDGERENTRIES.LIST"):
            pos = le.find("ISDEEMEDPOSITIVE").text
            amt = float(le.find("AMOUNT").text)
            # Debit → ISDEEMEDPOSITIVE Yes + negative amount; Credit → No + positive.
            assert (pos == "Yes" and amt < 0) or (pos == "No" and amt > 0)


def test_tally_xml_strips_xml_illegal_control_chars():
    """Qodo: uploaded settlement id/UTR with XML-1.0-forbidden control characters must not produce a
    non-well-formed Tally download — illegal code points are stripped before serialization."""
    row = ReconRow(
        entity_id="pay_1", type="payment", amount_paise=1000000, fee_paise=1000, tax_paise=180,
        debit_paise=0, credit_paise=999000, settlement_id="setl_\x01\x02X", settlement_utr="U\x0bTR",
        settled_at=datetime(2026, 6, 10), created_at=datetime(2026, 6, 10),
        on_hold=False, dispute_id=None, order_id=None, method="card", description=None,
    )
    xml = to_tally_xml(build_journal_entries([_recon(["pay_1"], 999000)], [row]))
    ET.fromstring(xml)  # raises if control chars leaked through and broke well-formedness


def test_deterministic_on_real_data():
    lines = load_bank("data/bank_statement.csv")
    recon = load_recon("data/recon_report.json")
    attrs = attribute_all(lines, ReconIndex(recon), 0.55)
    recs, _u, _s = reconcile({ln.key: ln for ln in lines}, attrs, recon)
    a = build_journal_entries(recs, recon)
    b = build_journal_entries(recs, recon)
    assert to_tally_xml(a) == to_tally_xml(b)
    assert to_journal_json(a) == to_journal_json(b)
    # One balanced voucher per reconciled credit; all balance.
    assert len(a) == len(recs)
    assert all(e.balanced for e in a)

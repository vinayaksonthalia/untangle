import json
from datetime import date, datetime

import pytest

from engine.evidence import ReconIndex
from engine.feegst import fee_gst
from engine.ingest import load_recon
from engine.investigate import investigate
from engine.journal import build_journal_entries
from engine.models import (
    BankCreditLine,
    EvidenceItem,
    Rail,
    RailAttribution,
    ReconciliationResult,
    ReconRow,
)
from engine.proof import build_proof_packets
from engine.reconcile import reconcile


def _row(fee, tax, row_id=None):
    return ReconRow("same", "payment", 10000 + fee, fee, tax, 0, 10000, "s", "u",
                    datetime(2026, 1, 1), datetime(2026, 1, 1), False, None, None, "upi", None, row_id)


def test_duplicate_key_uses_nonfirst_physical_row_everywhere():
    rows = [_row(100, 18), _row(700, 126)]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["recon_1"])
    assert fee_gst([rec], rows).total_recoverable_paise == 126
    entry = build_journal_entries([rec], rows)[0]
    assert entry.balanced
    assert any(line.debit_paise == 574 for line in entry.lines)  # 700 fee less 126 GST


def test_caller_row_ids_are_not_trusted_for_physical_identity():
    rows = [_row(100, 18, "duplicate"), _row(700, 126, "duplicate")]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["recon_1"])
    assert fee_gst([rec], rows).total_recoverable_paise == 126


def test_missing_covered_identity_fails_closed():
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["missing"])
    with pytest.raises(ValueError):
        fee_gst([rec], [_row(100, 18)])
    with pytest.raises(ValueError):
        build_journal_entries([rec], [_row(100, 18)])


def test_public_reconcile_propagates_nonfirst_duplicate():
    wrong = ReconRow("same", "payment", 9000, 100, 18, 0, 9000, "s0", "1111222233334444", datetime(2026,1,1), datetime(2026,1,1), False, None, None, "upi", "wrong")
    right = ReconRow("same", "payment", 10000, 700, 126, 0, 10000, "s1", "9999000011zzzz99", datetime(2026,1,1), datetime(2026,1,1), False, None, None, "upi", "right")
    line = BankCreditLine("k", date(2026,1,1), 10000, "RZP 9999000011zzzz99", None, True)
    attr = RailAttribution("k", Rail.RAZORPAY_SETTLEMENT.value, .99, "A", [EvidenceItem("utr_exact", "exact", 1)])
    results, _, _ = reconcile({"k": line}, [attr], [wrong, right])
    assert results[0].covered_row_ids == ["recon_1"]
    assert fee_gst(results, [wrong, right]).total_recoverable_paise == 126
    packets = build_proof_packets([line], [attr], results, [wrong, right], fee_gst(results, [wrong, right]))
    assert packets[0]["settlement"]["covered_entities"][0]["row_id"] == "recon_1"
    assert build_journal_entries(results, [wrong, right])[0].balanced
    inv = investigate(line, attr, results[0], [wrong, right], ReconIndex([wrong, right]))
    assert inv.variance_paise == 0  # expected net came from the selected second row


def test_load_recon_ignores_duplicate_vendor_ids(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps([{"entity_id":"x","type":"payment","amount":1,"credit":1,"row_id":"dup"},{"entity_id":"x","type":"payment","amount":2,"credit":2,"row_id":"dup"}]))
    rows = load_recon(str(p))
    assert [r.row_id for r in rows] == ["recon_0", "recon_1"]

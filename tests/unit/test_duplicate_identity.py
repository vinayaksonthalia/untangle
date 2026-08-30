import json
from datetime import date, datetime

import pytest

from engine.covered import canonical_row_ids
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


def _cids(rows):
    """Canonical (content-derived) covered ids in list order — what reconcile threads through."""
    ids = canonical_row_ids(rows)
    return [ids[id(r)] for r in rows]


def test_duplicate_key_uses_nonfirst_physical_row_everywhere():
    rows = [_row(100, 18), _row(700, 126)]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, [_cids(rows)[1]])
    assert fee_gst([rec], rows).total_recoverable_paise == 126
    entry = build_journal_entries([rec], rows)[0]
    assert entry.balanced
    assert any(line.debit_paise == 574 for line in entry.lines)  # 700 fee less 126 GST


def test_caller_row_ids_are_not_trusted_for_physical_identity():
    rows = [_row(100, 18, "duplicate"), _row(700, 126, "duplicate")]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, [_cids(rows)[1]])
    assert fee_gst([rec], rows).total_recoverable_paise == 126


def test_canonical_id_is_position_independent():
    # The two rows differ only in fee/tax; reordering them must NOT change which physical row a
    # covered id resolves to — the flaw a bare recon_<position> id could not prevent.
    rows = [_row(100, 18), _row(700, 126)]
    cid_of_700 = _cids(rows)[1]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, [cid_of_700])
    assert fee_gst([rec], rows).total_recoverable_paise == 126
    # Reorder recon_rows; the same id still selects the 700/126 row, not position 1.
    reordered = [rows[1], rows[0]]
    assert fee_gst([rec], reordered).total_recoverable_paise == 126


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
    assert results[0].covered_row_ids == [_cids([wrong, right])[1]]
    assert fee_gst(results, [wrong, right]).total_recoverable_paise == 126
    packets = build_proof_packets([line], [attr], results, [wrong, right], fee_gst(results, [wrong, right]))
    assert packets[0]["settlement"]["covered_entities"][0]["row_id"] == _cids([wrong, right])[1]
    assert packets[0]["fee_gst_recoverable_inr"] == "₹1.26"
    assert build_journal_entries(results, [wrong, right])[0].balanced
    entry = build_journal_entries(results, [wrong, right])[0]
    assert entry.utr == right.settlement_utr
    assert any(x.debit_paise == 574 for x in entry.lines)
    assert not any(x.debit_paise == 82 for x in entry.lines)
    inv = investigate(line, attr, results[0], [wrong, right], ReconIndex([wrong, right]))
    assert inv.variance_paise == 0  # expected net came from the selected second row


def test_load_recon_ignores_duplicate_vendor_ids(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps([{"entity_id":"x","type":"payment","amount":1,"credit":1,"row_id":"dup"},{"entity_id":"x","type":"payment","amount":2,"credit":2,"row_id":"dup"}]))
    rows = load_recon(str(p))
    assert [r.row_id for r in rows] == ["recon_0", "recon_1"]


def test_proof_and_investigation_fail_closed_on_identity_mismatch():
    row = _row(100, 18)
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["missing"])
    line = BankCreditLine("k", date(2026, 1, 1), 10000, "RZP", None, True)
    attr = RailAttribution("k", Rail.RAZORPAY_SETTLEMENT.value, .99, "A", [EvidenceItem("utr_exact", "exact", 1)])
    with pytest.raises(ValueError):
        build_proof_packets([line], [attr], [rec], [row], fee_gst([], []))
    with pytest.raises(ValueError):
        investigate(line, attr, rec, [row], ReconIndex([row]))


def test_duplicate_row_id_in_covered_fails_closed():
    # A reused physical row id would count one row twice — reject it everywhere.
    rows = [_row(100, 18), _row(700, 126)]
    dup = _cids(rows)[0]
    rec = ReconciliationResult(
        "k", [("payment", "same"), ("payment", "same")], 20000, 20000, 0, True, [dup, dup]
    )
    with pytest.raises(ValueError):
        fee_gst([rec], rows)
    with pytest.raises(ValueError):
        build_journal_entries([rec], rows)


def test_covered_row_id_resolving_to_wrong_entity_fails_closed():
    # The covered id resolves to a ("payment", "same") row but the covered entity tuple claims a
    # different entity_id — the row and the entity list have drifted apart, so accounting must stop.
    rows = [_row(100, 18)]
    rec = ReconciliationResult("k", [("payment", "other")], 10000, 10000, 0, True, [_cids(rows)[0]])
    with pytest.raises(ValueError):
        fee_gst([rec], rows)
    with pytest.raises(ValueError):
        build_journal_entries([rec], rows)


def test_id_bearing_rec_with_empty_entities_fails_closed_in_investigation():
    # covered_row_ids present but covered_entity_ids empty: the strict resolver's count-parity check
    # must fire in investigate() too, not slip into unresolved-credit behavior (Qodo #31 review-2).
    rows = [_row(100, 18)]
    rec = ReconciliationResult("k", [], 10000, 10000, 0, True, [_cids(rows)[0]])
    line = BankCreditLine("k", date(2026, 1, 1), 10000, "RZP", None, True)
    attr = RailAttribution("k", Rail.RAZORPAY_SETTLEMENT.value, .99, "A", [EvidenceItem("utr_exact", "exact", 1)])
    with pytest.raises(ValueError):
        investigate(line, attr, rec, rows, ReconIndex(rows))

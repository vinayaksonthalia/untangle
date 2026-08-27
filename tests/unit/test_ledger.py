"""Order-ledger reconciliation — per-reason-code detectors on crafted batches (Feature 003).

Discrepancy checks are scoped to the PROVEN (balanced) reconciled slice, so each test supplies a
balanced ReconciliationResult covering the order under test.
"""

from __future__ import annotations

from datetime import datetime

from engine.ledger import reconcile_ledger
from engine.models import OrderLedgerEntry, ReconciliationResult, ReconRow


def _row(order_id, entity_id="pay_1", type_="payment", amount=100000, dispute_id=None, sid="setl_1"):
    return ReconRow(entity_id, type_, amount, 0, 0, 0, amount, sid, "1780498800xp8vma",
                    datetime(2026, 6, 10), datetime(2026, 6, 9), False, dispute_id, order_id, "upi", None)


def _order(order_id, amount=100000, status="paid"):
    return OrderLedgerEntry(order_id=order_id, amount_paise=amount, status=status,
                            created_at=datetime(2026, 6, 10))


def _reconciled(*entity_ids_types):
    """A balanced reconciliation covering the given (type, entity_id) pairs."""
    covered = list(entity_ids_types) or [("payment", "pay_1")]
    return ReconciliationResult("k1", covered, 100000, 100000, 0, True)


def _codes(exceptions):
    return {e.reason_code for e in exceptions}


def test_empty_ledger_yields_nothing():
    assert reconcile_ledger([], [_reconciled()], [_row("order_a")]) == []


def test_ledger_mismatch_missing_settled_order():
    # order in a BALANCED reconciliation (money confirmed) but absent from the ledger.
    recon = [_row("order_settled", entity_id="pay_1")]
    excs = reconcile_ledger([_order("unrelated")], [_reconciled(("payment", "pay_1"))], recon)
    assert "ledger_mismatch" in _codes(excs)
    assert "missing" in next(e for e in excs if e.reason_code == "ledger_mismatch").detail.lower()


def test_ledger_mismatch_status_conflict_only_for_settled():
    recon = [_row("order_x", entity_id="pay_1")]
    # settled order with a contradicting ledger status → mismatch
    excs = reconcile_ledger([_order("order_x", status="failed")], [_reconciled(("payment", "pay_1"))], recon)
    assert "ledger_mismatch" in _codes(excs)
    # but WITHOUT a reconciliation (not proven settled), no status verdict is drawn
    assert reconcile_ledger([_order("order_x", status="failed")], [], recon) == []


def test_ledger_mismatch_amount_conflict():
    recon = [_row("order_x", entity_id="pay_1", amount=100000)]
    excs = reconcile_ledger([_order("order_x", amount=250000)], [_reconciled(("payment", "pay_1"))], recon)
    assert "ledger_mismatch" in _codes(excs)
    assert "amount" in next(e for e in excs if e.reason_code == "ledger_mismatch").detail.lower()


def test_ambiguous_duplicate_abstains_on_status():
    # a doubly-booked settled order is reported ONLY as a duplicate — no status/amount verdict.
    recon = [_row("order_dup", entity_id="pay_1")]
    ledger = [_order("order_dup", status="failed"), _order("order_dup", status="paid")]
    excs = reconcile_ledger(ledger, [_reconciled(("payment", "pay_1"))], recon)
    assert "duplicate_order_booking" in _codes(excs)
    assert "ledger_mismatch" not in _codes(excs)  # abstained on the ambiguous status


def test_duplicate_order_booking():
    recon = [_row("order_dup", entity_id="pay_1")]
    excs = reconcile_ledger([_order("order_dup"), _order("order_dup")],
                            [_reconciled(("payment", "pay_1"))], recon)
    assert "duplicate_order_booking" in _codes(excs)
    # a duplicate order NOT in the proven settled slice is not flagged (scoped to the covered slice)
    assert "duplicate_order_booking" not in _codes(
        reconcile_ledger([_order("order_dup"), _order("order_dup")], [], recon)
    )


def test_refund_not_reflected_only_when_no_row_records_refund():
    recon = [_row("order_r", entity_id="pay_1"),
             _row("order_r", entity_id="rfnd_1", type_="refund")]
    # the reconciled settlement covers BOTH the payment and the refund entity.
    rec = _reconciled(("payment", "pay_1"), ("refund", "rfnd_1"))
    # ledger marks paid, no refund row → flagged
    assert "refund_not_reflected" in _codes(reconcile_ledger([_order("order_r", status="paid")], [rec], recon))
    # ledger already records a refund → NOT flagged (checks ALL rows, not the first)
    assert "refund_not_reflected" not in _codes(
        reconcile_ledger([_order("order_r", status="paid"), _order("order_r", status="refunded")], [rec], recon)
    )


def test_summary_is_bounded_and_deterministic():
    recon = [_row(f"order_{i}", entity_id=f"pay_{i}") for i in range(50)]
    covered = [("payment", f"pay_{i}") for i in range(50)]
    ledger = [_order("unrelated_booked_order")]  # non-empty, but none of the 50 settled orders
    excs = reconcile_ledger(ledger, [_reconciled(*covered)], recon)  # all 50 settled, none booked
    mm = [e for e in excs if e.reason_code == "ledger_mismatch"]
    assert len(mm) == 1 and "50 settled orders" in mm[0].detail  # one summary, not 50
    # deterministic
    assert reconcile_ledger(ledger, [_reconciled(*covered)], recon) == excs

"""fee-GST is a faithful sum of Razorpay's own tax-on-fee over reconciled rows."""

from __future__ import annotations

from engine.feegst import fee_gst
from engine.models import FeeGstRecovery, ReconciliationResult, ReconRow


def _row(eid: str, tax: int) -> ReconRow:
    return ReconRow(
        entity_id=eid, type="payment", amount_paise=100000, fee_paise=2900,
        tax_paise=tax, debit_paise=0, credit_paise=97100, settlement_id="setl_1",
        settlement_utr="1568176960vxp0rj", settled_at=None, created_at=None,
        on_hold=False, dispute_id=None, order_id="order_1", method="card",
        description=None,
    )


def test_total_equals_sum_of_tax_over_covered_rows():
    rows = [_row("pay_a", 442), _row("pay_b", 0), _row("pay_c", 118)]
    rec = ReconciliationResult(
        line_key="k", covered_entity_ids=[("payment", "pay_a"), ("payment", "pay_b"),
                                          ("payment", "pay_c")],
        covered_net_paise=291300, credit_amount_paise=291300, residual_paise=0, balanced=True,
    )
    out = fee_gst([rec], rows)
    assert isinstance(out, FeeGstRecovery)
    assert out.total_recoverable_paise == 442 + 118          # zero-tax row contributes nothing
    assert ("pay_a", 442) in out.by_entity                   # traceable per entity
    assert all(eid != "pay_b" for eid, _ in out.by_entity)   # zero-tax not listed


def test_duplicate_type_entity_rows_are_not_collapsed():
    """Regression: two distinct recon rows sharing the same (type, entity_id) — which the domain
    genuinely produces — must BOTH be counted. A plain last-wins dict double-counted the survivor and
    dropped the shadowed row, disagreeing with the journal's posted ITC. The multimap consumes one
    distinct row per covered-key occurrence."""
    a1 = _row("pay_dup", 442)   # first occurrence, tax 442
    a2 = _row("pay_dup", 118)   # second distinct row, SAME key, tax 118
    rec = ReconciliationResult(
        line_key="k",
        covered_entity_ids=[("payment", "pay_dup"), ("payment", "pay_dup")],  # key appears twice
        covered_net_paise=194200, credit_amount_paise=194200, residual_paise=0, balanced=True,
    )
    out = fee_gst([rec], [a1, a2])
    assert out.total_recoverable_paise == 442 + 118      # both rows counted, not 118+118 or just one
    assert sorted(t for _, t in out.by_entity) == [118, 442]


def test_no_reconciliations_means_zero():
    assert fee_gst([], [_row("pay_a", 442)]).total_recoverable_paise == 0

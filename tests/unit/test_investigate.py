"""Unit tests for the Agentic Exception-Investigation Loop (engine/investigate.py).

Tests every root-cause class in the §3b taxonomy:
1. mdr_fee_drift
2. cross_cycle_refund_lag
3. on_hold_release
4. dispute_deduction
5. partial_capture
6. bank_charge_or_rounding
7. rolling_reserve (gated on real data in schema)
8. unexplained (abstention over guess with candidates_tried)

Plus non-negotiable guarantees:
- 100% deterministic decision path (no LLM required)
- Every emitted corrective journal entry strictly balances (Debits == Credits)
- Deterministic confidence scoring
"""

from __future__ import annotations

from datetime import date, datetime

from engine.evidence import ReconIndex
from engine.investigate import (
    ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING,
    ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG,
    ROOT_CAUSE_DISPUTE_DEDUCTION,
    ROOT_CAUSE_MDR_FEE_DRIFT,
    ROOT_CAUSE_ON_HOLD_RELEASE,
    ROOT_CAUSE_PARTIAL_CAPTURE,
    ROOT_CAUSE_ROLLING_RESERVE,
    ROOT_CAUSE_UNEXPLAINED,
    investigate,
)
from engine.models import (
    BankCreditLine,
    ReconciliationResult,
    ReconRow,
)


def _make_bank_line(key: str, amount_paise: int, val_date: str = "2024-04-10") -> BankCreditLine:
    return BankCreditLine(
        key=key,
        value_date=date.fromisoformat(val_date),
        amount_paise=amount_paise,
        narration=f"CMS/ RAZORPAY SETTLEMENT / {key} / RATN0000001",
        bank_ref="RATN0000001",
        is_credit=True,
    )


def _make_payment_row(
    entity_id: str,
    amount_paise: int,
    fee_paise: int,
    tax_paise: int,
    settlement_id: str = "setl_001",
    on_hold: bool = False,
    dispute_id: str | None = None,
    description: str | None = None,
) -> ReconRow:
    debit_paise = fee_paise
    credit_paise = amount_paise
    return ReconRow(
        entity_id=entity_id,
        type="payment",
        amount_paise=amount_paise,
        fee_paise=fee_paise,
        tax_paise=tax_paise,
        debit_paise=debit_paise,
        credit_paise=credit_paise,
        settlement_id=settlement_id,
        settlement_utr="UTR123456",
        settled_at=datetime(2024, 4, 10, 12, 0, 0),
        created_at=datetime(2024, 4, 9, 10, 0, 0),
        on_hold=on_hold,
        dispute_id=dispute_id,
        order_id=f"order_{entity_id}",
        method="card",
        description=description,
    )


def _assert_entry_balanced(entry: dict | None) -> None:
    assert entry is not None, "Corrective entry must not be None for matched root cause"
    assert entry.get("balanced") is True, f"Corrective entry must be marked balanced: {entry}"
    lines = entry.get("lines", [])
    assert len(lines) >= 2, "Entry must have at least one debit and one credit line"
    total_debit = sum(
        round(float(ln["debit_inr"].replace("₹", "").replace(",", "").strip()) * 100)
        for ln in lines
    )
    total_credit = sum(
        round(float(ln["credit_inr"].replace("₹", "").replace(",", "").strip()) * 100)
        for ln in lines
    )
    assert total_debit == total_credit, f"Debits ({total_debit}) != Credits ({total_credit})"


def test_investigate_mdr_fee_drift():
    """Test MDR fee tax inside/outside drift is classified and balances."""
    # Expected net: ₹10,000 gross - ₹236 fee (tax ₹36) = ₹9,764 net (976400 paise).
    # Bank receives ₹9,728 (972800 paise) because tax was excluded from settlement net (delta: -₹36 = -3600 paise).
    line = _make_bank_line("line_mdr", 972800)
    row = _make_payment_row("pay_01", amount_paise=1000000, fee_paise=23600, tax_paise=3600)
    recon_rows = [row]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_01")],
        covered_net_paise=976400,
        credit_amount_paise=line.amount_paise,
        residual_paise=-3600,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_MDR_FEE_DRIFT
    assert inv.variance_paise == -3600
    assert inv.confidence >= 0.90
    _assert_entry_balanced(inv.corrective_entry)
    assert any("mdr_fee_drift" in step.lower() for step in inv.reasoning_trace)
    assert any("₹36.00" in step for step in inv.reasoning_trace)


def test_investigate_cross_cycle_refund_lag():
    """Test cross-cycle refund lag is identified and drafts a balanced suspense entry."""
    # Expected net: ₹5,000 (500000 paise). Bank receives ₹4,500 (450000 paise) (delta: -₹500 = -50000 paise).
    # A refund of ₹500 was processed.
    line = _make_bank_line("line_refund", 450000)
    pay_row = _make_payment_row("pay_02", amount_paise=500000, fee_paise=0, tax_paise=0)
    refund_row = ReconRow(
        entity_id="rfnd_01",
        type="refund",
        amount_paise=50000,
        fee_paise=0,
        tax_paise=0,
        debit_paise=50000,
        credit_paise=0,
        settlement_id="setl_001",
        settlement_utr="UTR123456",
        settled_at=datetime(2024, 4, 12, 10, 0, 0),  # Later cycle
        created_at=datetime(2024, 4, 10, 8, 0, 0),
        on_hold=False,
        dispute_id=None,
        order_id="order_pay_02",
        method="card",
        description="Refund timing lag",
    )
    recon_rows = [pay_row, refund_row]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_02")],
        covered_net_paise=500000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-50000,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG
    assert inv.variance_paise == -50000
    assert inv.confidence >= 0.90
    _assert_entry_balanced(inv.corrective_entry)
    assert any("cross_cycle_refund_lag" in step.lower() for step in inv.reasoning_trace)


def test_cross_cycle_refund_lag_does_not_force_fit_unrelated_settlement():
    """Regression: a refund of the exact variance amount that belongs to a DIFFERENT settlement must
    NOT be classified as cross_cycle_refund_lag. Scanning the whole dataset (the original bug) would
    force-fit any coincidental amount match — a guess, not evidence. It must abstain instead."""
    line = _make_bank_line("line_unrelated_refund", 450000)  # variance -₹500 vs the covered ₹5,000 net
    pay_row = _make_payment_row("pay_x", amount_paise=500000, fee_paise=0, tax_paise=0)  # setl_001
    # A refund whose amount EXACTLY equals the variance, but in an unrelated settlement (setl_999).
    unrelated_refund = ReconRow(
        entity_id="rfnd_other", type="refund", amount_paise=50000, fee_paise=0, tax_paise=0,
        debit_paise=50000, credit_paise=0, settlement_id="setl_999", settlement_utr="UTRZZZ",
        settled_at=datetime(2024, 5, 12, 10, 0, 0), created_at=datetime(2024, 5, 10, 8, 0, 0),
        on_hold=False, dispute_id=None, order_id=None, method="card", description="unrelated refund",
    )
    recon_rows = [pay_row, unrelated_refund]
    rec = ReconciliationResult(
        line_key=line.key, covered_entity_ids=[("payment", "pay_x")], covered_net_paise=500000,
        credit_amount_paise=line.amount_paise, residual_paise=-50000, balanced=False,
    )
    inv = investigate(line, None, rec, recon_rows, ReconIndex(recon_rows))
    assert inv.root_cause != ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG  # never force-fit the unrelated refund
    assert inv.root_cause == ROOT_CAUSE_UNEXPLAINED             # no in-settlement cause → abstain
    assert inv.corrective_entry is None


def test_deduction_causes_do_not_match_a_positive_overage():
    """Regression (sign-awareness): a POSITIVE variance (bank received MORE than expected) must not be
    explained by a deduction cause (dispute/on-hold/refund) even when a deduction of the same magnitude
    exists. Deductions only close a negative (short) variance; a magnitude-only match was the bug."""
    # Expected net ₹5,000; bank receives ₹5,500 → +₹500 overage (positive variance).
    line = _make_bank_line("line_overage", 550000)
    pay = _make_payment_row("pay_ov", amount_paise=500000, fee_paise=0, tax_paise=0)
    # A dispute row whose amount equals the overage magnitude — must NOT be force-fit.
    disputed = _make_payment_row("pay_disp", amount_paise=50000, fee_paise=0, tax_paise=0)
    disputed = ReconRow(
        entity_id="pay_disp", type="payment", amount_paise=50000, fee_paise=0, tax_paise=0,
        debit_paise=0, credit_paise=50000, settlement_id="setl_001", settlement_utr="UTR123456",
        settled_at=datetime(2024, 4, 10, 12, 0, 0), created_at=datetime(2024, 4, 9, 10, 0, 0),
        on_hold=False, dispute_id="disp_1", order_id=None, method="card", description="",
    )
    recon_rows = [pay, disputed]
    rec = ReconciliationResult(
        line_key=line.key, covered_entity_ids=[("payment", "pay_ov")], covered_net_paise=500000,
        credit_amount_paise=line.amount_paise, residual_paise=50000, balanced=False,
    )
    inv = investigate(line, None, rec, recon_rows, ReconIndex(recon_rows))
    assert inv.variance_paise == 50000  # positive overage
    assert inv.root_cause not in (
        ROOT_CAUSE_DISPUTE_DEDUCTION, ROOT_CAUSE_ON_HOLD_RELEASE, ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG,
    )


def test_investigate_on_hold_release():
    """Test on-hold transaction deduction is classified."""
    # Expected net: ₹8,000 (800000 paise). Bank receives ₹6,000 (600000 paise).
    # Payment pay_03 (₹2,000) is flagged on_hold=True.
    line = _make_bank_line("line_on_hold", 600000)
    pay1 = _make_payment_row("pay_03a", amount_paise=600000, fee_paise=0, tax_paise=0)
    pay2 = _make_payment_row("pay_03b", amount_paise=200000, fee_paise=0, tax_paise=0, on_hold=True)
    recon_rows = [pay1, pay2]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_03a"), ("payment", "pay_03b")],
        covered_net_paise=800000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-200000,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_ON_HOLD_RELEASE
    assert inv.variance_paise == -200000
    assert inv.confidence >= 0.90
    _assert_entry_balanced(inv.corrective_entry)
    assert any("on_hold_release" in step.lower() for step in inv.reasoning_trace)


def test_investigate_dispute_deduction():
    """Test dispute deduction is classified."""
    # Expected net: ₹12,000. Bank receives ₹10,000.
    # Payment pay_04 has dispute_id="disp_999" for ₹2,000.
    line = _make_bank_line("line_dispute", 1000000)
    pay1 = _make_payment_row("pay_04a", amount_paise=1000000, fee_paise=0, tax_paise=0)
    pay2 = _make_payment_row("pay_04b", amount_paise=200000, fee_paise=0, tax_paise=0, dispute_id="disp_999")
    recon_rows = [pay1, pay2]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_04a"), ("payment", "pay_04b")],
        covered_net_paise=1200000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-200000,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_DISPUTE_DEDUCTION
    assert inv.variance_paise == -200000
    assert inv.confidence >= 0.90
    _assert_entry_balanced(inv.corrective_entry)
    assert any("disp_999" in step for step in inv.reasoning_trace)


def test_partial_capture_is_not_inferred_from_free_text():
    """partial_capture is NOT deterministically expressible on this schema (no authorized/captured
    amounts), so it must be SKIPPED — never inferred from a 'partial' word in a description. A row
    that merely mentions 'partial' must not be force-fit; the credit abstains instead."""
    line = _make_bank_line("line_partial", 750000)
    pay = _make_payment_row(
        "pay_05", amount_paise=250000, fee_paise=0, tax_paise=0,
        description="Partial capture variance",  # free text — must NOT drive a classification
    )
    recon_rows = [pay]
    rec = ReconciliationResult(
        line_key=line.key, covered_entity_ids=[("payment", "pay_05")], covered_net_paise=1000000,
        credit_amount_paise=line.amount_paise, residual_paise=-250000, balanced=False,
    )
    inv = investigate(line, None, rec, recon_rows, ReconIndex(recon_rows))

    assert inv.root_cause != ROOT_CAUSE_PARTIAL_CAPTURE   # never inferred from text
    assert inv.root_cause == ROOT_CAUSE_UNEXPLAINED        # nothing deterministic explains it → abstain
    assert inv.corrective_entry is None
    # And the skipped classifier is recorded transparently in the negative space.
    pc = next(c for c in inv.candidates_tried if c["root_cause"] == ROOT_CAUSE_PARTIAL_CAPTURE)
    assert pc["matched"] is False and "Skipped" in pc["reason"]


def test_investigate_bank_charge_or_rounding():
    """Test small residual within ±₹1 tolerance is classified as rounding."""
    line = _make_bank_line("line_rounding", 999940)  # 60 paise rounding drift
    pay = _make_payment_row("pay_06", amount_paise=1000000, fee_paise=0, tax_paise=0)
    recon_rows = [pay]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_06")],
        covered_net_paise=1000000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-60,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING
    assert inv.variance_paise == -60
    assert inv.confidence >= 0.85
    _assert_entry_balanced(inv.corrective_entry)


def test_investigate_rolling_reserve_gated_on_real_data():
    """Test rolling reserve is classified when explicit reserve row is in data, and skipped when absent."""
    # Case A: Real reserve row in settlement data
    line = _make_bank_line("line_reserve", 900000)
    pay = _make_payment_row("pay_07", amount_paise=1000000, fee_paise=0, tax_paise=0)
    reserve_row = ReconRow(
        entity_id="res_01",
        type="reserve",
        amount_paise=100000,
        fee_paise=0,
        tax_paise=0,
        debit_paise=100000,
        credit_paise=0,
        settlement_id="setl_001",
        settlement_utr="UTR123456",
        settled_at=datetime(2024, 4, 10, 12, 0, 0),
        created_at=datetime(2024, 4, 9, 10, 0, 0),
        on_hold=False,
        dispute_id=None,
        order_id=None,
        method=None,
        description="10% rolling reserve withheld",
    )
    recon_rows = [pay, reserve_row]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_07"), ("reserve", "res_01")],
        covered_net_paise=1000000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-100000,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)
    assert inv.root_cause == ROOT_CAUSE_ROLLING_RESERVE
    assert inv.variance_paise == -100000
    _assert_entry_balanced(inv.corrective_entry)

    # Case B: No reserve row in settlement data -> never fabricates a guess, abstains as unexplained
    recon_rows_no_reserve = [pay]
    index_no_res = ReconIndex(recon_rows_no_reserve)
    rec_no_res = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_07")],
        covered_net_paise=1000000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-100000,
        balanced=False,
    )
    inv_unexplained = investigate(line, None, rec_no_res, recon_rows_no_reserve, index_no_res)
    assert inv_unexplained.root_cause == ROOT_CAUSE_UNEXPLAINED
    assert inv_unexplained.corrective_entry is None


def test_investigate_unexplained_abstention():
    """Test that arbitrary variance without matching data abstains with unexplained and full candidates_tried."""
    line = _make_bank_line("line_mystery", 734567)  # Arbitrary delta of -265433 paise
    pay = _make_payment_row("pay_08", amount_paise=1000000, fee_paise=0, tax_paise=0)
    recon_rows = [pay]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_08")],
        covered_net_paise=1000000,
        credit_amount_paise=line.amount_paise,
        residual_paise=-265433,
        balanced=False,
    )

    inv = investigate(line, None, rec, recon_rows, index)

    assert inv.root_cause == ROOT_CAUSE_UNEXPLAINED
    assert inv.confidence == 0.0
    assert inv.corrective_entry is None
    assert len(inv.candidates_tried) == 7
    for cand in inv.candidates_tried:
        assert cand["matched"] is False
        assert "reason" in cand
        assert cand["unexplained_residual_paise"] > 0
    assert any("Abstaining with root_cause='unexplained'" in step for step in inv.reasoning_trace)


def test_deterministic_template_narration_no_llm():
    """Verify that investigation decision path and narration are 100% deterministic with zero LLM dependence."""
    line = _make_bank_line("line_det", 972800)
    row = _make_payment_row("pay_det", amount_paise=1000000, fee_paise=23600, tax_paise=3600)
    recon_rows = [row]
    index = ReconIndex(recon_rows)

    rec = ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_det")],
        covered_net_paise=976400,
        credit_amount_paise=line.amount_paise,
        residual_paise=-3600,
        balanced=False,
    )

    inv1 = investigate(line, None, rec, recon_rows, index)
    inv2 = investigate(line, None, rec, recon_rows, index)

    # Identical runs produce identical dictionaries
    assert inv1.to_dict() == inv2.to_dict()
    assert isinstance(inv1.reasoning_trace, list)
    assert len(inv1.reasoning_trace) >= 3

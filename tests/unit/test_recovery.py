"""Unit tests for Active Recovery Controller diagnosis & hypotheses (Phase 1 / T1.2)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from engine.evidence import ReconIndex
from engine.models import (
    BankCreditLine,
    EvidenceItem,
    ExceptionRecord,
    Rail,
    RailAttribution,
    ReconRow,
)
from engine.recovery import (
    BLOCKING_AMBIGUOUS_SETSUM,
    BLOCKING_BRAND_NO_TIE,
    BLOCKING_LEDGER_EXCEPTION,
    BLOCKING_UNKNOWN_SENDER,
    BLOCKING_WEAK_UTR_SUFFIX,
    Hypothesis,
    RecoveryAction,
    RecoveryPlan,
    diagnose,
)


def _line(key: str, narr: str = "x", ref: str | None = None, amount: int = 100000, vd: str = "2026-06-10") -> BankCreditLine:
    return BankCreditLine(
        key=key,
        value_date=date.fromisoformat(vd),
        amount_paise=amount,
        narration=narr,
        bank_ref=ref,
        is_credit=True,
    )


def _empty_index() -> ReconIndex:
    return ReconIndex([])


def _index_with_utr(utr: str, net: int = 100000, dt: date = date(2026, 6, 10)) -> ReconIndex:
    row = ReconRow(
        entity_id="pay_1",
        type="payment",
        amount_paise=net,
        fee_paise=0,
        tax_paise=0,
        debit_paise=0,
        credit_paise=net,
        settlement_id="setl_1",
        settlement_utr=utr,
        settled_at=datetime.combine(dt, datetime.min.time()),
        created_at=datetime.combine(dt, datetime.min.time()),
        on_hold=False,
        dispute_id=None,
        order_id=None,
        method="upi",
        description=None,
    )
    return ReconIndex([row])


def test_diagnose_brand_no_tie():
    """Brand present but no settlement UTR/amount tie -> brand_no_tie."""
    line = _line("k1", narr="NEFT-RAZORPAY-SOFTWARE-PVT-LTD-SETTLEMENT")
    idx = _empty_index()
    ev = [EvidenceItem("narration_brand_rzp", "found brand 'razorpay'", 0.15)]
    attr = RailAttribution("k1", Rail.UNKNOWN.value, 0.0, "none", ev, abstained=True)
    exc = ExceptionRecord(
        line_key="k1",
        reason_code="razorpay_uncertain",
        detail="partial Razorpay signal but below confidence threshold",
        suggested_action="confirm against settlement report",
        evidence=ev,
    )

    hyps = diagnose(line, attr, idx, exc)
    assert len(hyps) >= 1
    rzp_hyp = next((h for h in hyps if h.rail == Rail.RAZORPAY_SETTLEMENT.value), None)
    assert rzp_hyp is not None
    assert rzp_hyp.blocking_reason == BLOCKING_BRAND_NO_TIE
    assert rzp_hyp.weight > 0.0
    assert rzp_hyp.line_key == "k1"


def test_diagnose_weak_suffix():
    """Weak/mangled UTR suffix only -> weak_utr_suffix."""
    idx = _index_with_utr("1780498800xp8vma", net=999999, dt=date(2026, 5, 1))
    # Narration has mangled suffix token xp8vma without 10-digit epoch prefix, date far away
    line = _line("k2", narr="REV-AXIS-XP8VMA-SETTLEMENT", ref=None, amount=100000, vd="2026-06-10")
    ev = [EvidenceItem("utr_suffix_weak", "suffix matches settlement UTR", 0.50)]
    attr = RailAttribution("k2", Rail.UNKNOWN.value, 0.0, "none", ev, abstained=True)
    exc = ExceptionRecord(
        line_key="k2",
        reason_code="razorpay_uncertain",
        detail="partial Razorpay signal",
        suggested_action="confirm UTR",
        evidence=ev,
    )

    hyps = diagnose(line, attr, idx, exc)
    assert len(hyps) >= 1
    rzp_hyp = next((h for h in hyps if h.rail == Rail.RAZORPAY_SETTLEMENT.value), None)
    assert rzp_hyp is not None
    assert rzp_hyp.blocking_reason == BLOCKING_WEAK_UTR_SUFFIX
    assert rzp_hyp.weight > 0.0


def test_diagnose_ambiguous_setsum():
    """Multiple satisfying settlement subsets sum to amount -> ambiguous_setsum."""
    line = _line("k3", narr="NEFT-RZP-SETTLEMENT-SPLIT", amount=500000)
    ev = [EvidenceItem("multiple_satisfying_subsets", "multiple subsets sum to amount", 0.0)]
    attr = RailAttribution("k3", Rail.UNKNOWN.value, 0.0, "none", ev, abstained=True)
    exc = ExceptionRecord(
        line_key="k3",
        reason_code="multiple_satisfying_subsets",
        detail="ambiguous set-sum",
        suggested_action="verify manually",
        evidence=ev,
    )

    hyps = diagnose(line, attr, _empty_index(), exc)
    assert len(hyps) >= 1
    rzp_hyp = next((h for h in hyps if h.rail == Rail.RAZORPAY_SETTLEMENT.value), None)
    assert rzp_hyp is not None
    assert rzp_hyp.blocking_reason == BLOCKING_AMBIGUOUS_SETSUM


def test_diagnose_unknown_sender():
    """No distinctive rail keywords at all -> unknown_sender."""
    line = _line("k4", narr="NEFT CR 0098234 TRANSFER FROM CORP ACCT")
    attr = RailAttribution("k4", Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
    exc = ExceptionRecord(
        line_key="k4",
        reason_code="unattributed_ambiguous",
        detail="no distinctive rail signal",
        suggested_action="assign rail manually",
        evidence=[],
    )

    hyps = diagnose(line, attr, _empty_index(), exc)
    assert len(hyps) == 1
    h = hyps[0]
    assert h.rail == Rail.UNKNOWN.value
    assert h.weight == 0.0
    assert h.blocking_reason == BLOCKING_UNKNOWN_SENDER


@pytest.mark.parametrize("code", ["ledger_mismatch", "duplicate_order_booking", "refund_not_reflected"])
def test_diagnose_ledger_exception(code):
    """A REAL ledger-class exception (engine/ledger.py) -> ledger_exception. Uses only codes the engine
    actually emits — not invented ones."""
    line = _line("k5", narr="RAZORPAY SETTLEMENT 1780498800xp8vma", ref="1780498800xp8vma")
    ev = [EvidenceItem("utr_exact", "exact tie", 0.95)]
    attr = RailAttribution("k5", Rail.RAZORPAY_SETTLEMENT.value, 0.95, "A", ev, abstained=False)
    exc = ExceptionRecord(
        line_key="k5",
        reason_code=code,
        detail="ledger discrepancy",
        suggested_action="reconcile against the order ledger",
        evidence=ev,
    )

    hyps = diagnose(line, attr, _empty_index(), exc)
    rzp_hyp = next((h for h in hyps if h.rail == Rail.RAZORPAY_SETTLEMENT.value), None)
    assert rzp_hyp is not None
    assert rzp_hyp.blocking_reason == BLOCKING_LEDGER_EXCEPTION
    assert rzp_hyp.weight == 0.95


def test_diagnose_competing_hypotheses():
    """Credit with signals for multiple rails produces competing hypotheses sorted by weight."""
    line = _line("k6", narr="PAYU PAYMENTS AND RAZORPAY MENTION")
    ev = [
        EvidenceItem("narration_pattern:other_gateway", "payu", 0.85),
        EvidenceItem("narration_brand_rzp", "razorpay", 0.15),
    ]
    attr = RailAttribution("k6", Rail.UNKNOWN.value, 0.0, "none", ev, abstained=True)
    exc = ExceptionRecord(
        line_key="k6",
        reason_code="razorpay_uncertain",
        detail="partial Razorpay signal",
        suggested_action="check",
        evidence=ev,
    )

    hyps = diagnose(line, attr, _empty_index(), exc)
    assert len(hyps) >= 2
    # Ensure descending weight order
    weights = [h.weight for h in hyps]
    assert weights == sorted(weights, reverse=True)
    rails = {h.rail for h in hyps}
    assert Rail.OTHER_GATEWAY.value in rails
    assert Rail.RAZORPAY_SETTLEMENT.value in rails


def test_diagnose_determinism_and_immutability():
    """diagnose is pure: repeated calls return identical results, inputs not mutated."""
    line = _line("k7", narr="NEFT-RAZORPAY-12345")
    ev = [EvidenceItem("narration_brand_rzp", "razorpay", 0.15)]
    attr = RailAttribution("k7", Rail.UNKNOWN.value, 0.0, "none", ev, abstained=True)
    exc = ExceptionRecord(
        line_key="k7",
        reason_code="razorpay_uncertain",
        detail="check",
        suggested_action="check",
        evidence=ev,
    )
    idx = _empty_index()

    h1 = diagnose(line, attr, idx, exc)
    h2 = diagnose(line, attr, idx, exc)
    assert h1 == h2

    # Verify input attributes intact
    assert attr.abstained is True
    assert line.key == "k7"


def test_dataclasses_frozen_and_serialization():
    """Verify Hypothesis, RecoveryAction, RecoveryPlan are frozen and serialize cleanly."""
    h = Hypothesis("k1", "razorpay_settlement", 0.85, "brand_no_tie")
    with pytest.raises((AttributeError, TypeError)):
        h.weight = 0.99  # type: ignore[misc]

    h_dict = h.to_dict()
    assert h_dict == {
        "line_key": "k1",
        "rail": "razorpay_settlement",
        "weight": 0.85,
        "blocking_reason": "brand_no_tie",
    }

    action = RecoveryAction(
        action_type="export_settlement_report",
        params={"date_from": "2026-06-05", "date_to": "2026-06-15"},
        resolves=("k1", "k2"),
        recoverable_paise=250000,
        cost=1.0,
        gain_per_cost=250000.0,
    )
    with pytest.raises((AttributeError, TypeError)):
        action.cost = 2.0  # type: ignore[misc]

    a_dict = action.to_dict()
    assert a_dict["action_type"] == "export_settlement_report"
    assert a_dict["resolves"] == ["k1", "k2"]

    plan = RecoveryPlan(
        actions=(action,),
        unresolved_count=2,
        unresolved_paise=250000,
        recoverable_if_actioned_paise=250000,
    )
    with pytest.raises((AttributeError, TypeError)):
        plan.unresolved_count = 5  # type: ignore[misc]

    p_dict = plan.to_dict()
    assert p_dict["unresolved_count"] == 2
    assert len(p_dict["actions"]) == 1

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
    ACTION_CLASSIFY_COUNTERPARTY,
    ACTION_CONFIRM_UTR_WITH_BANK,
    ACTION_EXPORT_SETTLEMENT_REPORT,
    ACTION_PROVIDE_SETTLEMENT_IDS,
    ACTION_RECONCILE_ORDER_LEDGER,
    BLOCKING_AMBIGUOUS_SETSUM,
    BLOCKING_BRAND_NO_TIE,
    BLOCKING_LEDGER_EXCEPTION,
    BLOCKING_UNKNOWN_SENDER,
    BLOCKING_WEAK_UTR_SUFFIX,
    Hypothesis,
    RecoveryAction,
    RecoveryPlan,
    build_recovery_plan,
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


def test_build_recovery_plan_grouping():
    """Two credits sharing the same action_type and params are grouped into ONE action."""
    l1 = _line("k1", narr="NEFT-RAZORPAY-SOFTWARE-PVT-LTD", amount=100000, vd="2026-06-10")
    l2 = _line("k2", narr="NEFT-RAZORPAY-SOFTWARE-PVT-LTD", amount=200000, vd="2026-06-10")
    ev1 = [EvidenceItem("narration_brand_rzp", "brand razorpay", 0.15)]
    ev2 = [EvidenceItem("narration_brand_rzp", "brand razorpay", 0.15)]
    a1 = RailAttribution("k1", Rail.UNKNOWN.value, 0.0, "none", ev1, abstained=True)
    a2 = RailAttribution("k2", Rail.UNKNOWN.value, 0.0, "none", ev2, abstained=True)
    exc1 = ExceptionRecord("k1", "razorpay_uncertain", "partial signal", "check", evidence=ev1)
    exc2 = ExceptionRecord("k2", "razorpay_uncertain", "partial signal", "check", evidence=ev2)

    plan = build_recovery_plan([l1, l2], [a1, a2], _empty_index(), [exc1, exc2])
    assert plan.unresolved_count == 2
    assert plan.unresolved_paise == 300000
    assert plan.recoverable_if_actioned_paise == 300000
    assert len(plan.actions) == 1

    action = plan.actions[0]
    assert action.action_type == ACTION_EXPORT_SETTLEMENT_REPORT
    assert action.resolves == ("k1", "k2")
    assert action.recoverable_paise == 300000
    assert action.cost == 1.0
    assert action.gain_per_cost == 300000.0


def test_build_recovery_plan_ranking_by_gain_per_cost():
    """Actions are ranked by gain_per_cost descending."""
    # Action A: unknown_sender, cost 0.5, amount 100000 -> gain_per_cost = 200000.0
    l_a = _line("ka", narr="NEFT CR TRANSFER A", amount=100000, vd="2026-06-10")
    a_a = RailAttribution("ka", Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
    exc_a = ExceptionRecord("ka", "unattributed_ambiguous", "no signal", "check", evidence=[])

    # Action B: brand_no_tie, cost 1.0, amount 500000 -> gain_per_cost = 500000.0
    l_b = _line("kb", narr="NEFT-RAZORPAY-B", amount=500000, vd="2026-06-10")
    ev_b = [EvidenceItem("narration_brand_rzp", "brand", 0.15)]
    a_b = RailAttribution("kb", Rail.UNKNOWN.value, 0.0, "none", ev_b, abstained=True)
    exc_b = ExceptionRecord("kb", "razorpay_uncertain", "brand", "check", evidence=ev_b)

    # Action C: weak_suffix, cost 2.0, amount 600000 -> gain_per_cost = 300000.0
    idx_c = _index_with_utr("1780498800xp8vma", net=999999, dt=date(2026, 5, 1))
    l_c = _line("kc", narr="REV-AXIS-XP8VMA-SETTLEMENT", amount=600000, vd="2026-06-10")
    ev_c = [EvidenceItem("utr_suffix_weak", "suffix", 0.5)]
    a_c = RailAttribution("kc", Rail.UNKNOWN.value, 0.0, "none", ev_c, abstained=True)
    exc_c = ExceptionRecord("kc", "razorpay_uncertain", "weak", "check", evidence=ev_c)

    plan = build_recovery_plan([l_a, l_b, l_c], [a_a, a_b, a_c], idx_c, [exc_a, exc_b, exc_c])
    assert len(plan.actions) == 3
    # Expected order: B (500000), C (300000), A (200000)
    assert plan.actions[0].action_type == ACTION_EXPORT_SETTLEMENT_REPORT
    assert plan.actions[0].gain_per_cost == 500000.0
    assert plan.actions[1].action_type == ACTION_CONFIRM_UTR_WITH_BANK
    assert plan.actions[1].gain_per_cost == 300000.0
    assert plan.actions[2].action_type == ACTION_CLASSIFY_COUNTERPARTY
    assert plan.actions[2].gain_per_cost == 200000.0


def test_build_recovery_plan_tie_breaking():
    """Equal gain_per_cost ties are broken by recoverable_paise desc, then action_type asc."""
    # Action 1: amount 100000, cost 1.0 -> gain = 100000.0, recoverable = 100000
    l1 = _line("k1", narr="NEFT-RAZORPAY-1", amount=100000, vd="2026-06-10")
    ev1 = [EvidenceItem("narration_brand_rzp", "brand", 0.15)]
    a1 = RailAttribution("k1", Rail.UNKNOWN.value, 0.0, "none", ev1, abstained=True)
    exc1 = ExceptionRecord("k1", "razorpay_uncertain", "brand", "check", evidence=ev1)

    # Action 2: amount 50000, cost 0.5 -> gain = 100000.0, recoverable = 50000
    l2 = _line("k2", narr="NEFT CR TRANSFER 2", amount=50000, vd="2026-06-10")
    a2 = RailAttribution("k2", Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
    exc2 = ExceptionRecord("k2", "unattributed_ambiguous", "no signal", "check", evidence=[])

    plan = build_recovery_plan([l1, l2], [a1, a2], _empty_index(), [exc1, exc2])
    assert len(plan.actions) == 2
    # Action 1 has higher recoverable_paise (100000 vs 50000), so ranks first
    assert plan.actions[0].resolves == ("k1",)
    assert plan.actions[1].resolves == ("k2",)


def test_build_recovery_plan_no_double_counting():
    """Credits resolvable by actions are counted exactly once in recoverable_if_actioned_paise."""
    l1 = _line("k1", narr="NEFT-RAZORPAY-1", amount=100000, vd="2026-06-10")
    l2 = _line("k2", narr="NEFT CR TRANSFER 2", amount=200000, vd="2026-06-10")
    ev1 = [EvidenceItem("narration_brand_rzp", "brand", 0.15)]
    a1 = RailAttribution("k1", Rail.UNKNOWN.value, 0.0, "none", ev1, abstained=True)
    a2 = RailAttribution("k2", Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
    exc1 = ExceptionRecord("k1", "razorpay_uncertain", "brand", "check", evidence=ev1)
    exc2 = ExceptionRecord("k2", "unattributed_ambiguous", "no signal", "check", evidence=[])

    plan = build_recovery_plan([l1, l2], [a1, a2], _empty_index(), [exc1, exc2])
    assert plan.unresolved_paise == 300000
    assert plan.recoverable_if_actioned_paise == 300000


def test_build_recovery_plan_capping_with_note():
    """When actions exceed max_actions, output is capped and a note is recorded."""
    lines = []
    attrs = []
    excs = []
    # Create 25 lines on different dates so they produce 25 distinct actions
    for i in range(25):
        key = f"k_{i:02d}"
        d_str = f"2026-06-{i+1:02d}"
        line_item = _line(key, narr=f"TRANSFER {i}", amount=10000 * (i + 1), vd=d_str)
        a = RailAttribution(key, Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
        exc = ExceptionRecord(key, "unattributed_ambiguous", "no signal", "check", evidence=[])
        lines.append(line_item)
        attrs.append(a)
        excs.append(exc)

    plan = build_recovery_plan(lines, attrs, _empty_index(), excs, max_actions=10)
    assert len(plan.actions) == 10
    assert plan.unresolved_count == 25
    assert plan.note is not None
    assert "top 10" in plan.note


def test_build_recovery_plan_all_resolved():
    """When all credits are resolved, returns empty plan with zeros."""
    resolved_line = _line("k1", narr="RAZORPAY SETTLEMENT 1780498800xp8vma")
    ev = [EvidenceItem("utr_exact", "exact tie", 0.95)]
    a = RailAttribution("k1", Rail.RAZORPAY_SETTLEMENT.value, 0.95, "A", ev, abstained=False)

    plan = build_recovery_plan([resolved_line], [a], _empty_index(), [])
    assert plan.actions == ()
    assert plan.unresolved_count == 0
    assert plan.unresolved_paise == 0
    assert plan.recoverable_if_actioned_paise == 0
    assert plan.note is None


def test_build_recovery_plan_action_types():
    """Verify provide_settlement_ids and reconcile_order_ledger actions are generated."""
    line_setsum = _line("k_setsum", narr="RZP SPLIT", amount=500000)
    ev_setsum = [EvidenceItem("multiple_satisfying_subsets", "ambiguous", 0.0)]
    attr_setsum = RailAttribution("k_setsum", Rail.UNKNOWN.value, 0.0, "none", ev_setsum, abstained=True)
    exc_setsum = ExceptionRecord("k_setsum", "multiple_satisfying_subsets", "detail", "act", evidence=ev_setsum)

    line_ledger = _line("k_ledger", narr="RZP SETTLEMENT", amount=250000)
    attr_ledger = RailAttribution("k_ledger", Rail.RAZORPAY_SETTLEMENT.value, 0.95, "A", [], abstained=False)
    exc_ledger = ExceptionRecord("k_ledger", "ledger_mismatch", "mismatch", "reconcile", evidence=[])

    plan = build_recovery_plan(
        [line_setsum, line_ledger],
        [attr_setsum, attr_ledger],
        _empty_index(),
        [exc_setsum, exc_ledger],
    )
    action_types = {a.action_type for a in plan.actions}
    assert ACTION_PROVIDE_SETTLEMENT_IDS in action_types
    assert ACTION_RECONCILE_ORDER_LEDGER in action_types


def test_recovery_action_honest_description():
    """Human-readable descriptions frame amounts as 'up to ₹X ... if confirmed'."""
    action = RecoveryAction(
        action_type=ACTION_EXPORT_SETTLEMENT_REPORT,
        params={"date_from": "2026-06-05", "date_to": "2026-06-15"},
        resolves=("k1", "k2"),
        recoverable_paise=350000,
        cost=1.0,
        gain_per_cost=350000.0,
    )
    desc = action.description
    assert "up to ₹3,500.00" in desc
    assert "if confirmed" in desc
    assert "owed" not in desc.lower()



"""Unit tests for Phase 3: Global Competing-Explanation Margin (engine/solver.py).

Tests written FIRST [test-first]:
- Two equally-valid global explanations for a credit (same objective cost) cause the
  contested credits to ABSTAIN, carrying both competing explanations.
- When margin_threshold=0.0 (default), Phase 2 behavior is strictly unchanged.
- A clear winner whose margin exceeds margin_threshold is accepted (not abstained).
- Determinism: identical inputs produce byte-identical margin assessments.
"""

from __future__ import annotations

from datetime import date, datetime

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.models import BankCreditLine, Rail, ReconRow
from engine.solver import (
    build_candidate_graph,
    solve_assignment,
)


def _line(
    key: str,
    narr: str = "x",
    ref: str | None = None,
    amount: int = 100000,
    vd: str = "2026-06-10",
) -> BankCreditLine:
    return BankCreditLine(
        key=key,
        value_date=date.fromisoformat(vd),
        amount_paise=amount,
        narration=narr,
        bank_ref=ref,
        is_credit=True,
    )


def _row(
    sid: str,
    utr: str,
    net: int = 100000,
    dt: date = date(2026, 6, 10),
) -> ReconRow:
    return ReconRow(
        entity_id=f"pay_{sid}",
        type="payment",
        amount_paise=net,
        fee_paise=0,
        tax_paise=0,
        debit_paise=0,
        credit_paise=net,
        settlement_id=sid,
        settlement_utr=utr,
        settled_at=datetime.combine(dt, datetime.min.time()),
        created_at=datetime.combine(dt, datetime.min.time()),
        on_hold=False,
        dispute_id=None,
        order_id=None,
        method="upi",
        description=None,
    )


def _build_symmetric_tie_graph():
    """Two credits with symmetric exact UTR ties to two identical settlements."""
    u1 = "1780498800xp8vma"
    u2 = "1780498801xp8vmb"
    l1 = _line("k1", narr=f"NEFT-{u1}-SETTLEMENT", ref=u2, amount=100000, vd="2026-06-10")
    l2 = _line("k2", narr=f"NEFT-{u2}-SETTLEMENT", ref=u1, amount=100000, vd="2026-06-10")
    idx = ReconIndex([
        _row("s1", utr=u1, net=100000, dt=date(2026, 6, 10)),
        _row("s2", utr=u2, net=100000, dt=date(2026, 6, 10)),
    ])
    lines = [l1, l2]
    attrs = attribute_all(lines, idx, 0.55)
    return build_candidate_graph(lines, idx, attrs)


def test_two_equally_valid_global_explanations_abstain_under_margin():
    """Two equally-valid global assignments cause the contested credits to abstain carrying both explanations."""
    graph = _build_symmetric_tie_graph()

    # With margin_threshold=0.05, the tie (gap=0.0 <= 0.05) must force abstention
    result = solve_assignment(graph, margin_threshold=0.05)

    v1 = result.verdicts["k1"]
    v2 = result.verdicts["k2"]

    assert v1.abstained, "Credit k1 must abstain under competing global explanations"
    assert v2.abstained, "Credit k2 must abstain under competing global explanations"
    assert v1.rail == Rail.UNKNOWN.value
    assert v2.rail == Rail.UNKNOWN.value

    # Must carry both competing global explanations
    assert v1.competing_global_explanation is not None
    expl1 = v1.competing_global_explanation
    assert "chosen" in expl1
    assert "competing" in expl1
    assert expl1["objective_gap"] <= 0.05
    assert expl1["margin_threshold"] == 0.05
    assert expl1["chosen"]["target_id"] != expl1["competing"]["target_id"]

    assert v2.competing_global_explanation is not None
    expl2 = v2.competing_global_explanation
    assert "chosen" in expl2
    assert "competing" in expl2
    assert expl2["objective_gap"] <= 0.05


def test_margin_threshold_zero_preserves_phase2_behavior():
    """When margin_threshold=0.0 (default), Phase 2 behavior is strictly unchanged."""
    graph = _build_symmetric_tie_graph()

    # With margin_threshold=0.0, deterministic tie-breaking picks a world without abstaining
    result = solve_assignment(graph, margin_threshold=0.0)

    v1 = result.verdicts["k1"]
    v2 = result.verdicts["k2"]

    assert not v1.abstained
    assert not v2.abstained
    assert v1.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v2.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v1.competing_global_explanation is None
    assert v2.competing_global_explanation is None


def test_clear_margin_accepts_winner():
    """A credit with a decisive objective margin over its alternative is accepted."""
    # Credit 1 has an exact UTR to S1 (confidence 0.95)
    l1 = _line("k1", narr="NEFT-UTR_S1-RAZORPAY", amount=100000, vd="2026-06-10")
    idx = ReconIndex([_row("s1", utr="UTR_S1", net=100000, dt=date(2026, 6, 10))])
    lines = [l1]
    attrs = attribute_all(lines, idx, 0.55)
    graph = build_candidate_graph(lines, idx, attrs)

    # Even with margin_threshold=0.10, the alternative (abstain) has 100,000 unexplained paise
    result = solve_assignment(graph, margin_threshold=0.10)

    v1 = result.verdicts["k1"]
    assert not v1.abstained
    assert v1.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v1.target_id == "s1"
    assert v1.competing_global_explanation is None


def test_global_margin_determinism():
    """Running solve_assignment with margin_threshold repeatedly produces byte-identical results."""
    graph = _build_symmetric_tie_graph()

    res1 = solve_assignment(graph, margin_threshold=0.05)
    res2 = solve_assignment(graph, margin_threshold=0.05)

    assert res1.objective_cost == res2.objective_cost
    assert res1.consumed_settlements == res2.consumed_settlements
    assert res1.verdicts["k1"].competing_global_explanation == res2.verdicts["k1"].competing_global_explanation
    assert res1.verdicts["k2"].competing_global_explanation == res2.verdicts["k2"].competing_global_explanation

"""Unit tests for Phase 2: Exact Solver (engine/solver.py).

Tests written FIRST [test-first]:
- A settlement net cannot be consumed twice.
- A provable split group is recovered by the solver.
- THE FLAGSHIP TEST: A locally plausible single match is REJECTED because accepting it
  would leave another credit with no valid global explanation (global consistency wins
  over local greedy matching), and rejected_matches records the violated constraint.
- Date window and drift tolerances are respected.
- Determinism: identical inputs produce byte-identical assignments.
- Oversized / un-enumerable component fails closed to safe abstention without crashing.
- Empty graph safety.
"""

from __future__ import annotations

from datetime import date, datetime

from engine.attribute import _SPLIT_MAX_CANDIDATES, attribute_all
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


def test_settlement_net_cannot_be_consumed_twice():
    """Two competing credits cannot both consume the same settlement net."""
    # Both credits have an amount match to Settlement S1
    l1 = _line("k1", narr="TRANSFER 1", amount=100000, vd="2026-06-10")
    l2 = _line("k2", narr="TRANSFER 2", amount=100000, vd="2026-06-10")

    idx = ReconIndex([_row("s1", utr="UTR_S1", net=100000, dt=date(2026, 6, 10))])
    attrs = attribute_all([l1, l2], idx, 0.55)
    graph = build_candidate_graph([l1, l2], idx, attrs)

    result = solve_assignment(graph)

    # Exactly one credit may be assigned to s1
    assigned_to_s1 = [
        k for k, v in result.verdicts.items()
        if v.target_id == "s1" and v.rail == Rail.RAZORPAY_SETTLEMENT.value
    ]
    assert len(assigned_to_s1) <= 1
    # The other credit must be abstained
    unassigned = [k for k, v in result.verdicts.items() if v.abstained]
    assert len(unassigned) >= 1
    assert len(result.consumed_settlements) == 1
    assert "s1" in result.consumed_settlements


def test_provable_split_group_is_recovered():
    """A settlement net split across two credits is recovered as a provable split group."""
    l1 = _line("k_leg1", narr="RTGS-RATN0000088-SPLIT1", amount=40000, vd="2026-06-10")
    l2 = _line("k_leg2", narr="RAZORPAY SETTLEMENT SPLIT2", amount=60000, vd="2026-06-11")

    idx = ReconIndex([_row("s_split", utr="UTR_SPLIT", net=100000, dt=date(2026, 6, 10))])
    attrs = attribute_all([l1, l2], idx, 0.55)
    graph = build_candidate_graph([l1, l2], idx, attrs)

    result = solve_assignment(graph)

    v1 = result.verdicts["k_leg1"]
    v2 = result.verdicts["k_leg2"]

    assert not v1.abstained
    assert not v2.abstained
    assert v1.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v2.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v1.target_id == "s_split"
    assert v2.target_id == "s_split"
    assert v1.tier == "C"
    assert v2.tier == "C"
    assert set(v1.covered_split_keys) == {"k_leg1", "k_leg2"}
    assert "s_split" in result.consumed_settlements


def test_flagship_locally_plausible_single_match_rejected_for_global_consistency():
    """THE FLAGSHIP TEST: A locally plausible match is rejected because global consistency forces another assignment.

    Scenario:
    - Settlement S1 has net = 100,000 paise.
    - Credit A (amount 100,000) has an amount tie to S1, but ALSO carries a direct_upi narration pattern.
    - Credits B (40,000) and C (60,000) form a provable split group uniquely summing to S1, with no other options.
    - Local greedy choice: Credit A takes S1 -> Credits B and C are stranded (100,000 paise unexplained).
    - Global solver choice: B + C take S1, Credit A takes direct_upi -> 0 paise unexplained!
    - Result: Credit A's local match to S1 is REJECTED, and rejected_matches records the violated constraint.
    """
    # Credit A: amount 100,000, narration matches UPI
    l_a = _line("k_a", narr="UPI/CR/123456789012/JOHN DOE", amount=100000, vd="2026-06-10")
    # Credit B: amount 40,000, carries RATN IFSC
    l_b = _line("k_b", narr="RTGS-RATN0000088-PAYMENT", amount=40000, vd="2026-06-10")
    # Credit C: amount 60,000, carries brand
    l_c = _line("k_c", narr="RAZORPAY SETTLEMENT LEG2", amount=60000, vd="2026-06-10")

    idx = ReconIndex([_row("s1", utr="UTR_S1", net=100000, dt=date(2026, 6, 10))])
    lines = [l_a, l_b, l_c]
    attrs = attribute_all(lines, idx, 0.55)
    graph = build_candidate_graph(lines, idx, attrs)

    result = solve_assignment(graph)

    v_a = result.verdicts["k_a"]
    v_b = result.verdicts["k_b"]
    v_c = result.verdicts["k_c"]

    # Global consistency test: B and C get the Razorpay settlement S1
    assert v_b.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v_b.target_id == "s1"
    assert v_c.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v_c.target_id == "s1"

    # Credit A is routed to its true rail (direct_upi), NOT Razorpay
    assert v_a.rail == Rail.DIRECT_UPI.value

    # Verifiable explainability: Credit A's candidate match to S1 was rejected
    rejected_targets = [r["target_id"] for r in result.rejected_matches if "k_a" in r["credit_keys"]]
    assert "s1" in rejected_targets

    # Violated constraint is explicitly recorded
    s1_rejection = next(
        r for r in result.rejected_matches
        if "k_a" in r["credit_keys"] and r["target_id"] == "s1"
    )
    assert s1_rejection["violated_constraint"] == "settlement_already_consumed"
    assert "s1" in s1_rejection["detail"]


def test_date_window_and_tolerance_respected():
    """Credits outside the date window or drift tolerance are not matched to settlements."""
    # Drift = 50 paise (within ±100 paise drift tolerance) -> accepted
    l_drift = _line("k_drift", narr="RTGS-RATN0000088-SPLIT1", amount=50050, vd="2026-06-10")
    l_drift2 = _line("k_drift2", narr="RAZORPAY SPLIT2", amount=49950, vd="2026-06-10")
    idx_drift = ReconIndex([_row("s_drift", utr="UTR_DRIFT", net=100000, dt=date(2026, 6, 10))])

    attrs = attribute_all([l_drift, l_drift2], idx_drift, 0.55)
    graph = build_candidate_graph([l_drift, l_drift2], idx_drift, attrs)
    result = solve_assignment(graph)

    assert result.verdicts["k_drift"].rail == Rail.RAZORPAY_SETTLEMENT.value
    assert result.verdicts["k_drift"].residual_paise == 0

    # Credit with value date 15 days away (> 5 days window)
    l_distant = _line("k_distant", narr="TRANSFER REF 1", amount=100000, vd="2026-06-25")
    idx_distant = ReconIndex([_row("s_dist", utr="UTR_DIST", net=100000, dt=date(2026, 6, 10))])
    attrs_dist = attribute_all([l_distant], idx_distant, 0.55)
    graph_dist = build_candidate_graph([l_distant], idx_distant, attrs_dist)
    result_dist = solve_assignment(graph_dist)

    assert result_dist.verdicts["k_distant"].abstained


def test_solver_determinism():
    """Running solve_assignment repeatedly on the same graph produces byte-identical results."""
    l1 = _line("k1", narr="RAZORPAY 1780498800xp8vma", amount=150000)
    l2 = _line("k2", narr="UPI/CR/123456789012/JOHN", amount=50000)
    idx = ReconIndex([_row("setl_1", utr="1780498800xp8vma", net=150000)])
    lines = [l1, l2]
    attrs = attribute_all(lines, idx, 0.55)

    graph = build_candidate_graph(lines, idx, attrs)

    res1 = solve_assignment(graph)
    res2 = solve_assignment(graph)

    assert res1.objective_cost == res2.objective_cost
    assert res1.consumed_settlements == res2.consumed_settlements
    assert [(k, v.rail, v.target_id) for k, v in res1.verdicts.items()] == \
           [(k, v.rail, v.target_id) for k, v in res2.verdicts.items()]
    assert res1.rejected_matches == res2.rejected_matches


def test_oversized_un_enumerable_component_fails_closed_to_abstain():
    """Oversized components (> _SPLIT_MAX_CANDIDATES) fail closed to safe abstention without crashing."""
    lines = []
    for i in range(_SPLIT_MAX_CANDIDATES + 5):
        lines.append(
            _line(f"k_bulk_{i:02d}", narr="RATN0000088 SPLIT", amount=1000, vd="2026-06-10")
        )
    idx = ReconIndex([_row("s_large", utr="UTR_LARGE", net=2000, dt=date(2026, 6, 10))])
    attrs = attribute_all(lines, idx, 0.55)
    graph = build_candidate_graph(lines, idx, attrs)

    result = solve_assignment(graph)

    # All un-enumerable credits must safely abstain
    assert all(v.abstained for v in result.verdicts.values())
    assert len(result.consumed_settlements) == 0


def test_empty_graph_safe():
    """Empty assignment graph produces empty result with zero cost."""
    idx = ReconIndex([])
    graph = build_candidate_graph([], idx, [])
    result = solve_assignment(graph)

    assert result.verdicts == {}
    assert result.consumed_settlements == set()
    assert result.objective_cost == (0, 0, 0, 0.0, 0.0)
    assert result.rejected_matches == []

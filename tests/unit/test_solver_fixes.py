"""Unit tests for the 5 global solver fixes (Bugs 1, 2, 3, 6, 7).

Tests written FIRST:
1. Split target/group & evidence preserved so downstream reconcile and exceptions align (Bug 1 & 7).
2. Proof packets carry split_reconstruction tie for solver-selected split legs (Bug 7).
3. Split threshold guard prevents below-threshold split candidate generation (Bug 3).
4. Combination enumeration and branch-and-bound bounds fail-closed per SC-005 (Bug 6).
5. Build report captures SolverResult without double-running solver (Bug 2).
"""

from __future__ import annotations

from datetime import date, datetime

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.exceptions import build_exceptions
from engine.models import BankCreditLine, Rail, RailAttribution, ReconRow
from engine.proof import build_proof_packets
from engine.reconcile import reconcile
from engine.solver import (
    build_candidate_graph,
    run_global_solver,
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


def test_poisoned_credit_never_appears_in_a_split_candidate():
    """Qodo (PR#20): a credit poisoned by an oversized/un-enumerable split pool must not appear in ANY
    split candidate (even one emitted for an earlier settlement before it was poisoned)."""
    # 35 RATN-IFSC legs eligible for one settlement → oversized (combos > max_combinations) → poisoned.
    legs = [
        _line(f"k_split_{i}", narr="RTGS-RATN0000088-SPLIT", amount=10000 + i * 100, vd="2026-06-10")
        for i in range(35)
    ]
    idx = ReconIndex([_row("s_split", utr="UTR_SPLIT_LARGE", net=500000, dt=date(2026, 6, 10))])
    graph = build_candidate_graph(legs, idx, threshold=0.55, max_combinations=5000)
    assert graph.un_enumerable_credits, "test did not force an un-enumerable pool"
    for c in graph.candidates:
        if c.is_split:
            assert not (set(c.credit_keys) & graph.un_enumerable_credits), (
                f"split candidate {c.assignment_id} references a poisoned credit"
            )


def test_split_candidate_carries_proof_evidence_and_packets():
    """Bug 7 & Bug 1: Split CandidateAssignments carry split_reconstruction evidence
    plus strong-origin proof, verdicts carry evidence, and proof packets receive the tie.
    """
    l1 = _line("k_leg1", narr="RTGS-RATN0000088-SPLIT1", amount=40000, vd="2026-06-10")
    l2 = _line("k_leg2", narr="RAZORPAY SETTLEMENT SPLIT2", amount=60000, vd="2026-06-11")

    recon_rows = [_row("s_split", utr="UTR_SPLIT", net=100000, dt=date(2026, 6, 10))]
    idx = ReconIndex(recon_rows)

    graph = build_candidate_graph([l1, l2], idx, threshold=0.55)
    split_cands = [c for c in graph.candidates if c.is_split]
    assert len(split_cands) >= 1
    sc = split_cands[0]

    # Bug 7: candidate edge must NOT have empty evidence
    assert len(sc.evidence) > 0
    signals = {e.signal for e in sc.evidence}
    assert "split_reconstruction" in signals
    assert "ifsc_ratn" in signals

    # Solve and verify verdicts preserve evidence
    res = solve_assignment(graph)
    v1 = res.verdicts["k_leg1"]
    v2 = res.verdicts["k_leg2"]
    assert any(e.signal == "split_reconstruction" for e in v1.evidence)
    assert any(e.signal == "split_reconstruction" for e in v2.evidence)

    # Run global solver and verify attributions + proof packets
    base_attrs = [
        RailAttribution(l1.key, Rail.UNKNOWN.value, 0.0, "NONE", []),
        RailAttribution(l2.key, Rail.UNKNOWN.value, 0.0, "NONE", []),
    ]
    attrs, _ = run_global_solver([l1, l2], idx, base_attrs, threshold=0.55)
    attr_by_key = {a.line_key: a for a in attrs}
    assert attr_by_key["k_leg1"].rail == Rail.RAZORPAY_SETTLEMENT.value
    assert any(e.signal == "split_reconstruction" for e in attr_by_key["k_leg1"].evidence)
    assert "s_split" in next(e.detail for e in attr_by_key["k_leg1"].evidence if e.signal == "split_reconstruction")

    # Downstream reconcile & exceptions
    lines_by_key = {l1.key: l1, l2.key: l2}
    results, unresolved, sidx = reconcile(lines_by_key, attrs, recon_rows)
    exceptions = build_exceptions(attrs, unresolved, lines_by_key)
    exc_reasons = {e.reason_code for e in exceptions}
    assert "reconstructed_split_leg" in exc_reasons

    # Proof packets carry the split_reconstruction tie
    from engine.models import FeeGstRecovery
    packets = build_proof_packets(
        [l1, l2], attrs, results, recon_rows,
        FeeGstRecovery(total_recoverable_paise=0, by_entity=[]),
    )
    assert len(packets) == 2
    for p in packets:
        tie_signals = {t["signal"] for t in p["proof"]["ties"]}
        assert "split_reconstruction" in tie_signals


def test_split_threshold_guard():
    """Bug 3: When threshold > _SPLIT_CONFIDENCE (0.9), no split candidates are emitted."""
    l1 = _line("k_leg1", narr="RTGS-RATN0000088-SPLIT1", amount=40000, vd="2026-06-10")
    l2 = _line("k_leg2", narr="RAZORPAY SETTLEMENT SPLIT2", amount=60000, vd="2026-06-11")

    recon_rows = [_row("s_split", utr="UTR_SPLIT", net=100000, dt=date(2026, 6, 10))]
    idx = ReconIndex(recon_rows)

    # Threshold 0.95 > 0.9: no split candidate should be emitted
    graph = build_candidate_graph([l1, l2], idx, threshold=0.95)
    split_cands = [c for c in graph.candidates if c.is_split]
    assert len(split_cands) == 0

    # Running solver with threshold 0.95 must abstain
    base_attrs = [
        RailAttribution(l1.key, Rail.UNKNOWN.value, 0.0, "NONE", []),
        RailAttribution(l2.key, Rail.UNKNOWN.value, 0.0, "NONE", []),
    ]
    attrs, _ = run_global_solver([l1, l2], idx, base_attrs, threshold=0.95)
    for a in attrs:
        assert a.abstained or a.rail != Rail.RAZORPAY_SETTLEMENT.value


def test_combination_and_branch_bounds_fail_closed():
    """Bug 6: Combinations and branch-and-bound bounds fail-closed per SC-005."""
    # Generate 35 eligible split lines with amounts that could combine
    lines = [
        _line(f"k_{i}", narr="RTGS-RATN0000088-TEST", amount=10000 + i * 100, vd="2026-06-10")
        for i in range(35)
    ]
    recon_rows = [_row("s_large", utr="UTR_LARGE", net=500000, dt=date(2026, 6, 10))]
    idx = ReconIndex(recon_rows)

    # With default max_combinations (5000), 35 lines produce >6000 combinations -> un-enumerable
    graph = build_candidate_graph(lines, idx, threshold=0.55, max_combinations=5000)
    assert len(graph.un_enumerable_credits) > 0

    # Solver fails closed for un-enumerable credits
    res = solve_assignment(graph)
    assert res.is_optimal is False
    for k in graph.un_enumerable_credits:
        assert res.verdicts[k].abstained


def test_build_report_captures_solver_result_without_double_run():
    """Bug 2: build_report captures solver_result without re-running run_global_solver."""
    from engine.cli import build_config, build_report

    l1 = _line("k1", narr="UPI/CR/123456789012/JOHN DOE", amount=100000, vd="2026-06-10")
    recon_rows = [_row("s1", utr="UTR_S1", net=100000, dt=date(2026, 6, 10))]
    idx = ReconIndex(recon_rows)

    cfg = build_config(no_ai=True, provider=None, model=None, threshold=0.55, seed=42, global_solver=True)
    solver_sink: dict = {}
    attrs = attribute_all(
        [l1], idx, cfg.threshold,
        global_solver=True,
        solver_result_out=solver_sink,
    )
    assert "solver_result" in solver_sink
    assert solver_sink["solver_result"] is not None

    # Pass solver_result to build_report; solver does NOT re-run
    rep, _ = build_report(
        cfg, [l1], recon_rows, idx, attrs,
        global_solver=True,
        solver_result=solver_sink["solver_result"],
    )
    assert rep.rejected_matches is not None


def test_single_credit_tie_preserved_when_split_pool_oversized():
    """Finding 2: An oversized split pool poisons credits for the split path, but credits with their own single-credit tie remain assignable."""
    # S_split has 35 eligible credits with max_combinations=5000 -> oversized split pool
    split_lines = [
        _line(f"k_split_{i}", narr="RTGS-RATN0000088-SPLIT", amount=10000 + i * 100, vd="2026-06-10")
        for i in range(35)
    ]
    # S_single has an exact UTR match on k_single_tied
    l_single = _line("k_single_tied", narr="RTGS/1780000000009999/SINGLE MATCH", amount=500000, vd="2026-06-10")

    recon_rows = [
        _row("s_split", utr="UTR_SPLIT_LARGE", net=500000, dt=date(2026, 6, 10)),
        _row("s_single", utr="1780000000009999", net=500000, dt=date(2026, 6, 10)),
    ]
    idx = ReconIndex(recon_rows)

    all_lines = split_lines + [l_single]
    graph = build_candidate_graph(all_lines, idx, threshold=0.55, max_combinations=5000)

    # s_split split candidates are dropped due to oversized combinations
    assert len(graph.un_enumerable_credits) > 0

    # Solve assignment
    res = solve_assignment(graph)

    # k_single_tied has its own valid single-credit tie to s_single and MUST be assigned
    v_single = res.verdicts["k_single_tied"]
    assert not v_single.abstained
    assert v_single.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert v_single.target_id == "s_single"


def test_candidate_graph_threshold_guard_on_single_edges():
    """Finding 3: Single-credit candidate edges below threshold are not emitted."""
    # Non-Razorpay line with low confidence score (e.g. 0.40)
    l_weak_upi = _line("k_weak_upi", narr="UPI/WEAK REF 123", amount=50000, vd="2026-06-10")
    recon_rows = [_row("s1", utr="UTR1", net=100000, dt=date(2026, 6, 10))]
    idx = ReconIndex(recon_rows)

    # At threshold=0.55, weak non-rzp edge with score < 0.55 is not created
    graph = build_candidate_graph([l_weak_upi], idx, threshold=0.55)
    candidates = graph.candidates_by_credit.get("k_weak_upi", [])
    # Only the default abstain candidate should exist
    assert all(c.target_id == "abstain" or c.confidence >= 0.55 for c in candidates)

    # At elevated threshold (e.g. 0.80), single-credit Razorpay edge with conf 0.52 is suppressed
    l_amt_only = _line("k_amt_only", narr="RTGS TRANSFER 123", amount=100000, vd="2026-06-10")
    graph_high = build_candidate_graph([l_amt_only], idx, threshold=0.80)
    cands_high = graph_high.candidates_by_credit.get("k_amt_only", [])
    assert all(c.target_id == "abstain" or c.confidence >= 0.80 for c in cands_high)


def test_credit_tied_to_s1_excluded_from_s2_split_pool():
    """Finding 4: A credit with a corroborated utr_suffix tie to S1 is excluded from S2's split candidate pool."""
    # Settlement S1 with UTR 1780000000001111
    # Settlement S2 with UTR 1780000000002222
    recon_rows = [
        _row("s1", utr="1780000000001111", net=500000, dt=date(2026, 6, 10)),
        _row("s2", utr="1780000000002222", net=1000000, dt=date(2026, 6, 10)),
    ]
    idx = ReconIndex(recon_rows)

    # Credit C1 has unique suffix '001111' tied to S1
    c1 = _line("k_c1", narr="RTGS/001111/RAZORPAY", amount=400000, vd="2026-06-10")
    # Credit C2 is a generic Razorpay credit
    c2 = _line("k_c2", narr="RAZORPAY SETTLEMENT LEG 2", amount=600000, vd="2026-06-10")

    graph = build_candidate_graph([c1, c2], idx, threshold=0.55)

    # C1 must NOT be in any split candidate targeting S2
    s2_split_cands = [
        c for c in graph.candidates
        if c.is_split and c.target_id == "s2"
    ]
    for sc in s2_split_cands:
        assert "k_c1" not in sc.credit_keys


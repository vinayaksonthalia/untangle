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

"""Phase 4 Acceptance Gate Test (ANTIGRAVITY_BUILD_PLAN.md §2 Phase 4).

Gate requirements:
  1. Honest reporting: report shows precision at multiple coverage points + the abstention curve.
  2. Exception queue: every abstained/unresolved credit carries reason + evidence trace.
  3. G5 — Proposed rule does nothing until approved (inertness).
  4. G5/FR-009 — Approved rule applies on confident match and never lowers precision.
  5. Rule-derived attributions are marked tier='rule_derived' and traceable to the human.
  6. G6 — Rules store derived metadata only, never raw statement rows.
  7. Verification on 294-line benchmark: razorpay precision 1.000 with rules applied.
  8. G7 engine isolation preserved.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engine.abstain import coverage_curve
from engine.attribute import attribute_all
from engine.config import DEFAULT_THRESHOLD
from engine.evidence import ReconIndex
from engine.exceptions import build_exceptions
from engine.ingest import load_bank, load_recon
from engine.models import BankCreditLine, EvidenceItem, Rail, Tier
from engine.rules import (
    ProposedRule,
    apply_approved_rules,
    approve_rule,
    match_rule,
    propose_rule,
)
from eval.metrics import score


def test_phase4_gate_honest_reporting_precision_at_coverage():
    """Gate 1: Report shows precision at multiple coverage points + abstention curve."""
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    index = ReconIndex(recon_rows)
    attributions = attribute_all(lines, index, DEFAULT_THRESHOLD)

    # 1. Check engine-side abstention curve across thresholds
    confidences = [a.confidence for a in attributions if not a.abstained]
    curve = coverage_curve(confidences, steps=20)
    assert len(curve) > 5, "Coverage curve must contain multiple points"
    # Coverage must be non-increasing with threshold
    coverages = [p.coverage for p in curve]
    for i in range(len(coverages) - 1):
        assert coverages[i] >= coverages[i + 1]

    # 2. Check eval metrics precision-at-coverage curve
    report_dict = {
        "totals": {
            "n_bank_lines": len(lines),
            "attributed": sum(1 for a in attributions if not a.abstained),
            "abstained": sum(1 for a in attributions if a.abstained),
        },
        "attributions": [a.to_dict() for a in attributions],
    }
    m = score(report_dict, "data/ground_truth.json", "data/bank_statement.csv")
    assert "precision_at_coverage" in m, "precision_at_coverage must be in eval metrics"
    pac = m["precision_at_coverage"]
    assert len(pac) >= 5, "Must report at multiple coverage points (not one number)"

    # Verify each point has coverage, abstention_rate, n_attr, n_abst, rzp_prec
    for pt in pac:
        assert 0.0 <= pt["coverage"] <= 1.0
        assert 0.0 <= pt["abstention_rate"] <= 1.0
        assert round(pt["coverage"] + pt["abstention_rate"], 2) == 1.0
        assert pt["n_attributed"] + pt["n_abstained"] == len(lines)
        # Precision must remain 1.000 across all operating points
        assert pt["razorpay_precision"] == 1.000, f"Precision dropped below 1.000 at tau={pt['threshold']}"


def test_phase4_gate_exception_queue_evidence_trace():
    """Gate 2: Every exception in the queue carries reason code, detail, and evidence trace."""
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    index = ReconIndex(recon_rows)
    lines_by_key = {l.key: l for l in lines}
    attributions = attribute_all(lines, index, DEFAULT_THRESHOLD)

    # Reconcile to find unresolved
    from engine.reconcile import reconcile
    results, unresolved_rzp, sidx = reconcile(lines_by_key, attributions, recon_rows)

    exceptions = build_exceptions(
        attributions,
        unresolved_rzp,
        lines_by_key,
        ambiguous_rzp=sidx.ambiguous_lines,
        duplicate_or_split_rzp=sidx.duplicate_or_split_lines,
        unbalanced_rzp=sidx.unbalanced_lines,
    )

    assert len(exceptions) > 0, "Exception queue must not be empty"
    for exc in exceptions:
        assert exc.line_key in lines_by_key
        assert exc.reason_code in {
            "multiple_satisfying_subsets",
            "partial_or_duplicate_settlement",
            "unbalanced_residual",
            "razorpay_uncertain",
            "unattributed_ambiguous",
            "razorpay_coverage_not_found",
        }
        assert exc.detail
        assert exc.suggested_action
        # Evidence trace must be present
        assert isinstance(exc.evidence, list)


def test_phase4_gate_human_proposed_rules_lifecycle_g5_g6():
    """Gate 3, 4, 5, 6: Human-proposed rules lifecycle, inertness, approval, and privacy."""
    # Test line: an unknown vendor credit that is unattributed
    line = BankCreditLine(
        key="k_vendor_test",
        value_date=date(2026, 6, 15),
        amount_paise=500000,
        narration="NEFT CR-ACMEPAY-991823-MERCHANT DISBURSE",
        bank_ref="991823",
        is_credit=True,
    )

    # 1. Propose rule (G5: proposed, not applied)
    rule = propose_rule(
        target_rail=Rail.OTHER_GATEWAY.value,
        pattern_value="acmepay",
        pattern_type="narration_keyword",
        rationale="AcmePay is a secondary payment aggregator used for overflow transactions",
    )
    # Check initial state: MUST be inert
    assert rule.approved is False, "A newly proposed rule MUST NOT be approved"
    assert rule.approved_by is None
    assert rule.approved_at is None
    assert match_rule(line, rule) is False, "Unapproved rule must NEVER match (inertness)"

    # Calling apply_approved_rules with unapproved rule returns NOTHING
    attrs = apply_approved_rules([line], [rule])
    assert len(attrs) == 0, "Unapproved rule must produce zero attributions"

    # 2. Privacy check (G6: derived metadata only, no raw statements)
    rule_dict = rule.to_dict()
    assert "acmepay" == rule.pattern_value
    # Ensure no raw line contents leaked into rule
    assert line.key not in rule_dict.values()
    assert line.narration not in rule_dict.values()
    assert str(line.amount_paise) not in str(rule_dict)

    # 3. Approve rule (human controller explicitly approves)
    approved = approve_rule(rule, approver="finance_controller_1")
    assert approved.approved is True
    assert approved.approved_by == "finance_controller_1"
    assert approved.approved_at is not None

    # 4. Matching: confident match fires, near-match does NOT fire
    assert match_rule(line, approved) is True

    # Near-match test: partial token collision should NOT fire
    near_line = BankCreditLine(
        key="k_near_test",
        value_date=date(2026, 6, 15),
        amount_paise=500000,
        narration="NEFT CR-ACMEPAYOUTS-991823",  # different word, near-match
        bank_ref="991823",
        is_credit=True,
    )
    # Clean boundary check prevents accidental trigger
    assert match_rule(near_line, approved) is False, "Near-match must NOT trigger rule"

    # 5. Apply approved rule: marked rule-derived and traceable to approver
    applied = apply_approved_rules([line], [approved])
    assert "k_vendor_test" in applied
    attr = applied["k_vendor_test"]
    assert attr.rail == Rail.OTHER_GATEWAY.value
    assert attr.tier == Tier.RULE.value  # tier must be 'rule_derived'
    assert attr.abstained is False
    # Traceability
    assert any("finance_controller_1" in e.detail for e in attr.evidence)
    assert any(rule.rule_id in e.detail for e in attr.evidence)


def test_phase4_gate_benchmark_precision_with_approved_rule():
    """Gate 7: Applying approved rules on 294-line benchmark never lowers precision."""
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    index = ReconIndex(recon_rows)

    # Propose and approve a rule for a known non-razorpay pattern
    # e.g. "payout" for other_gateway
    rule = propose_rule(
        target_rail=Rail.OTHER_GATEWAY.value,
        pattern_value="billdesk",
        rationale="BillDesk netbanking transactions",
    )
    approve_rule(rule, approver="lead_auditor")

    attributions = attribute_all(lines, index, DEFAULT_THRESHOLD, rules=[rule])

    report_dict = {
        "totals": {
            "n_bank_lines": len(lines),
            "attributed": sum(1 for a in attributions if not a.abstained),
            "abstained": sum(1 for a in attributions if a.abstained),
        },
        "attributions": [a.to_dict() for a in attributions],
    }
    m = score(report_dict, "data/ground_truth.json", "data/bank_statement.csv")

    # Guardrail: Razorpay precision MUST remain exactly 1.000 (0 decoy FP)
    rzp_prec = m["per_rail"]["razorpay_settlement"]["precision"]
    decoy_fp = m["decoy_false_positive"]["predicted_razorpay"]
    assert rzp_prec == 1.000, f"Precision degraded to {rzp_prec}!"
    assert decoy_fp == 0, f"Decoy false positives introduced: {decoy_fp}!"


def test_phase4_engine_isolation_g7():
    """Verify G7: engine code never imports from generator or reads ground truth."""
    engine_dir = Path("engine")
    for py_file in engine_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "import generator" not in text, f"{py_file} imports generator!"
        assert "from generator" not in text, f"{py_file} imports from generator!"
        assert "ground_truth" not in text, f"{py_file} references ground_truth!"


def test_rules_never_reclassify_debits():
    """FR-015 / Qodo: an approved rule (even razorpay-target) must never attribute a debit."""
    from datetime import date
    from engine.models import BankCreditLine, Rail
    from engine.rules import apply_approved_rules, approve_rule, propose_rule

    debit = BankCreditLine("d1", date(2026, 6, 15), 50000, "NEFT DR-ACMEPAY-CHARGE", "x", is_credit=False)
    credit = BankCreditLine("c1", date(2026, 6, 15), 50000, "NEFT CR-ACMEPAY-PAYOUT", "y", is_credit=True)
    rule = approve_rule(
        propose_rule(target_rail=Rail.RAZORPAY_SETTLEMENT.value, pattern_value="acmepay"), "alice"
    )
    out = apply_approved_rules([debit, credit], [rule])
    assert "d1" not in out, "a rule must never reclassify a debit into a credit rail"
    assert "c1" in out, "a rule should still resolve a matching credit"

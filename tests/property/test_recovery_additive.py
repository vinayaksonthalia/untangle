"""Property: Active Recovery Controller is strictly ADDITIVE, deterministic, and empty-safe (Feature 005).

Non-negotiable constitution invariants (T4.2):
- Attaching the recovery plan must NOT change any attribution, reconciliation, fee-GST, or exception.
- Headline metrics (Razorpay precision 1.000, recall, reconciled count, fee-GST, totals) must be BYTE-IDENTICAL.
- Pure and deterministic: same inputs -> identical recovery plan.
- Empty-input safety: empty statements or recon reports run cleanly without error.
"""

from __future__ import annotations

import json

from engine.attribute import attribute_all
from engine.cli import build_report
from engine.config import build_config
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from eval.metrics import score

_HEADLINE_TOTAL_KEYS = [
    "by_rail_count",
    "by_rail_paise",
    "attributed",
    "abstained",
    "reconciled_count",
    "reconciled_paise",
    "unresolved_rzp_count",
    "fee_gst_recoverable_paise",
    "total_credit_paise",
    "exception_count",
]


def _setup_pipeline():
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42)
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    index = ReconIndex(recon_rows)
    attrs = attribute_all(lines, index, cfg.threshold)
    return cfg, lines, recon_rows, index, attrs


def test_recovery_step_is_strictly_additive_and_byte_identical():
    """GENUINE additivity: build the report WITH and WITHOUT the recovery step (two real builds) and prove
    the ONLY difference is the added recovery_plan key — every other section is byte-identical."""
    cfg, lines, recon_rows, index, attrs = _setup_pipeline()

    report_with, _ = build_report(cfg, lines, recon_rows, index, attrs, with_recovery=True)
    report_without, _ = build_report(cfg, lines, recon_rows, index, attrs, with_recovery=False)
    report_dict_with = report_with.to_dict()
    report_dict_without = report_without.to_dict()

    # The recovery build must actually add the plan; the no-recovery build must not.
    assert report_dict_with.get("recovery_plan") is not None
    assert report_dict_without.get("recovery_plan") is None

    # Every OTHER top-level section must be byte-identical between the two independent builds.
    for key in set(report_dict_with) | set(report_dict_without):
        if key == "recovery_plan":
            continue
        assert report_dict_with[key] == report_dict_without[key], f"recovery step altered section {key!r}"

    # Explicit headline-metric guard (redundant with the loop, but pins the invariant).
    for k in _HEADLINE_TOTAL_KEYS:
        assert report_dict_with["totals"][k] == report_dict_without["totals"][k]

    # Ground-truth metrics unchanged and precision still 1.000.
    score_with = score(report_dict_with, "data/ground_truth.json", "data/bank_statement.csv")
    score_without = score(report_dict_without, "data/ground_truth.json", "data/bank_statement.csv")
    rzp_pr_with = score_with["per_rail"]["razorpay_settlement"]
    rzp_pr_without = score_without["per_rail"]["razorpay_settlement"]
    assert rzp_pr_with["precision"] == rzp_pr_without["precision"] == 1.0000
    assert rzp_pr_with["recall"] == rzp_pr_without["recall"]
    assert rzp_pr_with["fp"] == rzp_pr_without["fp"] == 0

    # Recovery plan must be present, populated, and honestly framed.
    plan_dict = report_dict_with["recovery_plan"]
    assert plan_dict["unresolved_count"] > 0
    assert len(plan_dict["actions"]) > 0
    for action in plan_dict["actions"]:
        assert "up to" in action["description"]
        assert "if confirmed" in action["description"]
        assert "owed" not in action["description"].lower()


def test_recovery_plan_is_deterministic():
    """Building the recovery plan on identical inputs produces identical actions and ordering."""
    cfg, lines, recon_rows, index, attrs = _setup_pipeline()

    rep1, _ = build_report(cfg, lines, recon_rows, index, attrs)
    rep2, _ = build_report(cfg, lines, recon_rows, index, attrs)

    plan1 = rep1.to_dict()["recovery_plan"]
    plan2 = rep2.to_dict()["recovery_plan"]

    assert json.dumps(plan1, sort_keys=True) == json.dumps(plan2, sort_keys=True)


def test_recovery_empty_inputs_safe():
    """Empty bank lines or empty inputs produce valid, empty recovery plan without error."""
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42)
    index = ReconIndex([])
    report, _ = build_report(cfg, [], [], index, [])

    r_dict = report.to_dict()
    assert "recovery_plan" in r_dict
    plan = r_dict["recovery_plan"]
    assert plan["unresolved_count"] == 0
    assert plan["unresolved_paise"] == 0
    assert plan["recoverable_if_actioned_paise"] == 0
    assert plan["actions"] == []

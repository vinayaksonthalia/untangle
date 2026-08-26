"""Coverage-curve honesty (Qodo PR#2 reporting-honesty follow-up).

The coverage curve must use an HONEST denominator: coverage is the fraction of ALL lines
auto-attributed, so abstentions lower it. Excluding abstained lines from the denominator
(the old bug) reported ~100% coverage on a run that actually abstained on many lines.
"""

from __future__ import annotations

from engine.abstain import coverage_curve, required_precision


def test_coverage_denominator_counts_all_lines_not_just_attributed():
    # 3 auto-attributed lines (high confidence) + 7 abstentions in a 10-line batch.
    attributed_conf = [0.99, 0.98, 0.97]
    total_lines = 10

    curve = coverage_curve(attributed_conf, steps=20, total=total_lines)
    top = curve[0]  # tau = 0.0: every attributed line is covered
    assert top.coverage == 0.3, "coverage at tau=0 must be attributed/total = 3/10, not 1.0"

    # The honest curve must never report full coverage when abstentions exist.
    assert all(p.coverage <= 0.3 for p in curve)

    # Regression guard: the buggy call (denominator = attributed only) inflates to 1.0.
    buggy = coverage_curve(attributed_conf, steps=20)
    assert buggy[0].coverage == 1.0
    assert buggy[0].coverage > top.coverage


def test_coverage_is_monotonic_non_increasing_in_tau():
    curve = coverage_curve([0.2, 0.5, 0.9, 0.95], steps=20, total=8)
    covs = [p.coverage for p in curve]
    assert covs == sorted(covs, reverse=True)
    assert 0.0 <= covs[-1] <= covs[0] <= 1.0


def test_required_precision_matches_cost_ratio():
    # Default: a wrong match costs 20x a review -> require precision >= 0.95.
    assert round(required_precision(), 4) == 0.95
    assert required_precision(cost_wrong=0) == 0.0

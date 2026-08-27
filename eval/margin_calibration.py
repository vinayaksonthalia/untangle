"""Conformal calibration of the adversarial-challenger proof margin (Feature 004).

The challenger (``engine/challenger.py``) scores, for every machine Razorpay verdict, a ``proof_margin``
= how far the valid explanation beats the strongest counterfactual. This module chooses the margin
THRESHOLD at which a verdict is accepted, with a finite-sample precision guarantee.

Method (honest, distribution-aware):
  1. Collect every would-be Razorpay candidate's (margin, correct) on a labelled dataset.
  2. Over a predeclared grid of thresholds, accept candidates with ``margin >= t`` and count errors.
  3. Bound the accepted error rate with a one-sided exact Clopper-Pearson upper bound, Bonferroni-
     corrected across the whole grid so threshold *selection* is itself covered by the guarantee.
  4. Certify a threshold only if its precision lower bound >= target AND recall stays within budget.
  5. Pick the certified threshold with the most coverage; tie-break to the lower threshold.
  6. If none qualifies, FAIL CLOSED (return None) — the caller keeps the feature disabled.

Coverage is never called precision. The guarantee assumes the labelled set is exchangeable with
deployment; an adversarial benchmark alone cannot certify production precision under arbitrary shift.

CLI:  python -m eval.margin_calibration            # runs on the seeded dev dataset in data/
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from math import ceil, comb

from engine.attribute import _combine, attribute_all
from engine.challenger import challenge_razorpay
from engine.evidence import ReconIndex, narration_rail_signals
from engine.ingest import load_bank, load_recon
from engine.models import Rail

_RZP = Rail.RAZORPAY_SETTLEMENT.value


@dataclass(frozen=True)
class MarginCalibration:
    threshold: float
    precision: float
    precision_lower_bound: float
    candidate_coverage: float
    overall_coverage: float
    razorpay_recall: float
    accepted: int
    errors: int


# ---------------------------------------------------------------------------
# Clopper-Pearson one-sided upper bound on the error rate.
# ---------------------------------------------------------------------------
def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    total = 0.0
    for i in range(0, k + 1):
        total += comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
    return min(1.0, total)


def _clopper_pearson_upper(k: int, n: int, alpha: float) -> float:
    """Exact one-sided (1-alpha) upper confidence bound on the error probability.

    Solves for p such that P(Binom(n,p) <= k) = alpha (the CDF is monotone decreasing in p).
    k=0 and k=n handled by the binary search endpoints.
    """
    if n == 0:
        return 1.0
    if k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


# ---------------------------------------------------------------------------
# Calibration over the margin grid.
# ---------------------------------------------------------------------------
def calibrate_proof_margin(
    candidates: list[tuple[float, bool]],
    total_lines: int,
    baseline_razorpay_recall: float,
    *,
    target_precision: float = 0.99,
    confidence: float = 0.95,
    max_recall_drop: float = 0.01,
    grid_step: float = 0.005,
) -> MarginCalibration | None:
    """Certify a margin threshold, or None (fail closed).

    ``candidates`` are (margin, correct) for every would-be Razorpay verdict at threshold 0.
    ``baseline_razorpay_recall`` is the engine's Razorpay recall with the gate off; recall retention is
    measured relative to the baseline true-positive count so the reported recall is on the same scale.
    """
    if not candidates:
        return None
    if not (0.0 < grid_step <= 1.0):  # invalid grid → fail closed, never miscertify
        return None
    baseline_correct = sum(1 for _m, c in candidates if c)
    if baseline_correct == 0:
        return None

    # Predeclared grid over [0, 1] with a guaranteed 1.0 endpoint; Bonferroni over its exact size.
    grid = sorted({round(min(i * grid_step, 1.0), 6) for i in range(ceil(1.0 / grid_step) + 1)})
    alpha = (1.0 - confidence) / len(grid)

    best: MarginCalibration | None = None
    for t in grid:
        accepted = [(m, c) for m, c in candidates if m >= t]
        n = len(accepted)
        if n == 0:
            continue
        errors = sum(1 for _m, c in accepted if not c)
        accepted_correct = n - errors
        precision = accepted_correct / n
        upper = _clopper_pearson_upper(errors, n, alpha)
        precision_lb = 1.0 - upper
        recall_retention = accepted_correct / baseline_correct
        deployed_recall = baseline_razorpay_recall * recall_retention
        cand_cov = n / len(candidates)
        overall_cov = n / total_lines if total_lines else 0.0

        certified = (
            precision_lb >= target_precision
            and deployed_recall >= baseline_razorpay_recall - max_recall_drop
            and deployed_recall >= 0.90
        )
        if not certified:
            continue
        cand = MarginCalibration(
            threshold=t,
            precision=round(precision, 6),
            precision_lower_bound=round(precision_lb, 6),
            candidate_coverage=round(cand_cov, 6),
            overall_coverage=round(overall_cov, 6),
            razorpay_recall=round(deployed_recall, 6),
            accepted=n,
            errors=errors,
        )
        # maximise coverage; tie-break to the LOWER threshold (already ascending, so keep first max)
        if best is None or cand.candidate_coverage > best.candidate_coverage:
            best = cand
    return best


# ---------------------------------------------------------------------------
# Collect candidate margins on a labelled dataset.
# ---------------------------------------------------------------------------
def _truth_by_line_id(truth_path: str) -> dict[str, str]:
    d = json.load(open(truth_path, encoding="utf-8"))
    return {lab["line_id"]: lab["rail"] for lab in d.get("labels", [])}


def collect_candidate_margins(
    bank_csv: str = "data/bank_statement.csv",
    recon_json: str = "data/recon_report.json",
    truth_path: str = "data/ground_truth.json",
    threshold: float = 0.55,
) -> tuple[list[tuple[float, bool]], int, float]:
    """Return (candidates, total_lines, baseline_razorpay_recall) on a labelled dataset."""
    from eval.metrics import build_key_to_lineid

    lines = load_bank(bank_csv)
    index = ReconIndex(load_recon(recon_json))
    truth = _truth_by_line_id(truth_path)
    key_to_lineid = build_key_to_lineid(bank_csv)

    # Use attribute_all (gate off) so candidates cover EVERY machine Razorpay verdict — including the
    # Tier-C split-reconstruction legs that attribute_line alone would miss.
    attrs = attribute_all(lines, index, threshold, margin_threshold=0.0)
    line_by_key = {ln.key: ln for ln in lines}

    candidates: list[tuple[float, bool]] = []
    total_true_rzp = sum(1 for r in truth.values() if r == _RZP)
    baseline_correct = 0
    for a in attrs:
        if a.rail != _RZP or a.abstained:
            continue
        ln = line_by_key[a.line_key]
        res = challenge_razorpay(ln, index, a.evidence, narration_rail_signals(ln), a.confidence, _combine)
        correct = truth.get(key_to_lineid.get(ln.key, ""), "") == _RZP
        candidates.append((res.proof_margin, correct))
        if correct:
            baseline_correct += 1

    baseline_recall = baseline_correct / total_true_rzp if total_true_rzp else 0.0
    return candidates, len(lines), baseline_recall


def run(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="eval.margin_calibration")
    p.add_argument("--bank", default="data/bank_statement.csv")
    p.add_argument("--recon", default="data/recon_report.json")
    p.add_argument("--truth", default="data/ground_truth.json")
    p.add_argument("--target", type=float, default=0.99)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    for path in (args.bank, args.recon, args.truth):
        if not os.path.exists(path):
            print(f"missing input: {path} (generate the dataset first)", file=sys.stderr)
            return 2

    candidates, total, baseline_recall = collect_candidate_margins(
        args.bank, args.recon, args.truth
    )
    n_correct = sum(1 for _m, c in candidates if c)
    n_err = sum(1 for _m, c in candidates if not c)
    result = calibrate_proof_margin(candidates, total, baseline_recall, target_precision=args.target)

    margins = sorted(m for m, _c in candidates)
    summary = {
        "razorpay_candidates": len(candidates),
        "candidate_true_positives": n_correct,
        "candidate_false_positives": n_err,
        "baseline_razorpay_recall": round(baseline_recall, 6),
        "margin_min": round(margins[0], 6) if margins else None,
        "margin_median": round(margins[len(margins) // 2], 6) if margins else None,
        "certified": result.__dict__ if result else None,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("=" * 72)
    print("  ADVERSARIAL-CHALLENGER PROOF-MARGIN CALIBRATION")
    print("=" * 72)
    print(f"  Razorpay candidates (gate off) : {len(candidates)}")
    print(f"  ├─ true positives              : {n_correct}")
    print(f"  └─ false positives             : {n_err}")
    print(f"  Baseline Razorpay recall       : {baseline_recall:.3f}")
    if margins:
        print(f"  Proof-margin  min / median     : {margins[0]:.3f} / {margins[len(margins)//2]:.3f}")
    print("-" * 72)
    if result is None:
        if n_err == 0:
            print("  No benchmark false-positives to gate out — precision is already 1.000.")
            print("  Honest result: no POSITIVE threshold is certified (a positive threshold would only")
            print("  cut recall for no measured precision gain). The challenger stays INACTIVE in")
            print("  production (margin_threshold = 0.0): it does not run, so it neither gates nor")
            print("  annotates verdicts here. It is wired + tested, ready to enable when a benchmark")
            print("  with real false-positives certifies a threshold; its abstain-on-fragile behaviour")
            print("  is exercised by the crafted unit tests.")
        else:
            print("  FAIL CLOSED: no threshold meets the precision target within the recall budget.")
            print("  Feature stays disabled (margin_threshold = 0.0).")
    else:
        r = result
        print(f"  CERTIFIED margin threshold     : {r.threshold:.3f}")
        print(f"  Razorpay precision             : {r.precision:.4f}")
        print(f"  Precision lower bound (95%)    : {r.precision_lower_bound:.4f}  (target {args.target})")
        print(f"  Candidate coverage             : {r.candidate_coverage:.3f}  ({r.accepted}/{len(candidates)})")
        print(f"  Overall coverage               : {r.overall_coverage:.3f}")
        print(f"  Razorpay recall (deployed)     : {r.razorpay_recall:.3f}")
        print(f"  Accepted / errors              : {r.accepted} / {r.errors}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

"""Cost-model-derived abstention threshold and precision/coverage curve data
(spec FR-004, research R4).

The operating threshold τ is *justified*, not asserted. The justification:

    A wrong auto-attribution silently corrupts downstream reconciliation and the
    merchant's books; unwinding it costs far more than a ~2-minute human review of an
    escalation. If a wrong match costs ``cost_wrong`` and a review costs ``cost_review``,
    auto-attributing is only worth it where expected cost (1 − precision)·cost_wrong is
    below cost_review — i.e. where precision ≥ 1 − cost_review/cost_wrong.

With the default ratio (a wrong match ≈ 20× a review) that required precision is 0.95.
We report the precision/coverage curve so the chosen operating point is auditable; the
engine's runtime cutoff is a confidence threshold (default in ``config.DEFAULT_THRESHOLD``)
below which a line abstains (UNKNOWN).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COST_WRONG = 20.0   # relative units
DEFAULT_COST_REVIEW = 1.0


def required_precision(cost_wrong: float = DEFAULT_COST_WRONG,
                       cost_review: float = DEFAULT_COST_REVIEW) -> float:
    """Minimum precision at which auto-attribution beats always-escalating."""
    if cost_wrong <= 0:
        return 0.0
    return max(0.0, 1.0 - cost_review / cost_wrong)


@dataclass
class CurvePoint:
    threshold: float
    coverage: float          # fraction of lines auto-attributed at/above this threshold


def coverage_curve(
    confidences: list[float], steps: int = 20, total: int | None = None
) -> list[CurvePoint]:
    """Coverage as a function of the confidence cutoff (engine-side; no ground truth).

    ``confidences`` are the confidences of the *auto-attributed* (non-abstained) lines.
    ``total`` is the honest denominator — the count of ALL lines in the batch, so that
    abstentions lower coverage. When ``total`` is omitted it falls back to the number of
    confidences supplied (i.e. coverage of the attributed population only); production
    callers must pass ``total`` to avoid inflating coverage by excluding abstentions.
    """
    n = total if total is not None else len(confidences)
    n = n or 1
    pts: list[CurvePoint] = []
    for i in range(steps + 1):
        tau = i / steps
        covered = sum(1 for c in confidences if c >= tau)
        pts.append(CurvePoint(round(tau, 4), round(covered / n, 4)))
    return pts

"""Adversarial challenger & proof-margin (Feature 004).

Before a MACHINE Razorpay attribution is accepted, actively try to DISPROVE it: generate a bounded,
deterministic set of counterfactual ("challenger") explanations, score each with the SAME scoring
function used for the candidate (passed in as ``combine`` to avoid a circular import), and compute

    proof_margin = best_valid_rzp_score - best_competing_score

The margin is small exactly when the verdict is fragile — either a competing rail scores almost as
high, or the score survives mostly on *resemblance* signals (brand / IFSC / settlement_ref / date)
after the genuine tie is ablated away. The caller abstains when the margin is below a
conformally-calibrated threshold.

Pure and deterministic. Never mutates the line, the index, or any reconciliation state. The margin can
only ever demote a Razorpay verdict to an abstention — it never creates or upgrades a verdict.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from engine.models import EvidenceItem, Rail

CombineFn = Callable[[list[EvidenceItem]], float]

# The genuine tie signals (a real link back to the settlement report). Everything else a Razorpay
# credit carries — brand words, the Razorpay IFSC, a settlement-shaped-but-unlisted token, date
# proximity — is resemblance, not proof.
_UTR_SIGNALS = ("utr_exact", "utr_suffix", "utr_suffix_weak")
_AMOUNT_SIGNALS = ("amount_corr", "amount_corr_multi")
_ALL_TIE_SIGNALS = _UTR_SIGNALS + _AMOUNT_SIGNALS + ("setsum", "split_reconstruction")

_MAX_CHALLENGES = 16


@dataclass(frozen=True)
class CompetingExplanation:
    """One counterfactual explanation that competes with the Razorpay verdict."""

    operator: str
    rail: str
    score: float
    detail: str
    removed_signals: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "operator": self.operator,
            "rail": self.rail,
            "score": round(self.score, 6),
            "detail": self.detail,
            "removed_signals": list(self.removed_signals),
        }


@dataclass(frozen=True)
class ChallengerResult:
    rzp_score: float
    competing_score: float
    proof_margin: float
    strongest: CompetingExplanation | None
    challenges_evaluated: int
    truncated: bool = False
    challenges: tuple[CompetingExplanation, ...] = field(default_factory=tuple)


def _without(evidence: Sequence[EvidenceItem], drop: tuple[str, ...]) -> list[EvidenceItem]:
    dropset = set(drop)
    return [e for e in evidence if e.signal not in dropset]


def _ablation(
    evidence: Sequence[EvidenceItem],
    combine: CombineFn,
    operator: str,
    drop: tuple[str, ...],
    detail: str,
) -> CompetingExplanation | None:
    """Score the Razorpay evidence with a group of tie signals removed.

    A high residual score means the verdict leans on *resemblance*, not the tie we removed — that is
    a weak, challengeable verdict. Returns None when nothing was actually removed (no challenge).
    """
    present = tuple(s for s in drop if any(e.signal == s for e in evidence))
    if not present:
        return None
    residual = _without(evidence, drop)
    return CompetingExplanation(
        operator=operator,
        rail=Rail.RAZORPAY_SETTLEMENT.value,
        score=combine(residual),
        detail=detail,
        removed_signals=present,
    )


def challenge_razorpay(
    line,
    index,
    rzp_evidence: Sequence[EvidenceItem],
    non_rzp_evidence: Mapping[Rail, Sequence[EvidenceItem]],
    rzp_score: float,
    combine: CombineFn,
    *,
    max_challenges: int = _MAX_CHALLENGES,
) -> ChallengerResult:
    """Generate bounded counterfactuals and return the proof margin.

    ``line`` and ``index`` are accepted for interface stability and future operators (same-amount
    alternative, set-sum repartition); this implementation is pure over the evidence and never reads
    or mutates them.
    """
    challenges: list[CompetingExplanation] = []

    # 1. Observed competing rails — a distinctive non-Razorpay narration that scores on its own.
    for rail, items in non_rzp_evidence.items():
        if rail == Rail.RAZORPAY_SETTLEMENT:
            continue
        items = list(items)
        if not items:
            continue
        challenges.append(
            CompetingExplanation(
                operator="observed_competing_rail",
                rail=rail.value,
                score=combine(items),
                detail=f"distinctive {rail.value} narration remains plausible",
                removed_signals=(),
            )
        )

    # 2. Evidence ablations — does the verdict survive without each genuine tie?
    has_exact = any(e.signal == "utr_exact" for e in rzp_evidence)
    ablations = [
        ("drop_exact_identifier", _UTR_SIGNALS,
         "score without any UTR-identifier tie (leans on resemblance)"),
        ("drop_amount_tie", _AMOUNT_SIGNALS,
         "score without the amount-to-settlement tie"),
        ("drop_setsum", ("setsum", "split_reconstruction"),
         "score without the reconstructed set-sum"),
        ("drop_time_proximity", ("value_date_proximity",),
         "score without settlement-date proximity"),
        ("unlinked_rzp", _ALL_TIE_SIGNALS,
         "resemblance only — every genuine tie removed"),
    ]
    # drop_suffix only when there is no exact UTR (otherwise it is subsumed by drop_exact_identifier)
    if not has_exact:
        ablations.insert(1, ("drop_suffix", ("utr_suffix", "utr_suffix_weak"),
                             "score without the corroborated UTR suffix"))

    for operator, drop, detail in ablations:
        ch = _ablation(rzp_evidence, combine, operator, drop, detail)
        if ch is not None:
            challenges.append(ch)

    # Deterministic order and bounded work.
    challenges.sort(key=lambda c: (c.operator, c.rail, c.detail))
    truncated = len(challenges) > max_challenges
    if truncated:
        challenges = challenges[:max_challenges]

    competing_score = max((c.score for c in challenges), default=0.0)
    strongest = None
    if challenges:
        # highest score wins; deterministic tie-break by (operator, rail, detail)
        strongest = max(challenges, key=lambda c: (c.score, c.operator, c.rail, c.detail))
    proof_margin = rzp_score - competing_score

    return ChallengerResult(
        rzp_score=rzp_score,
        competing_score=competing_score,
        proof_margin=proof_margin,
        strongest=strongest,
        challenges_evaluated=len(challenges),
        truncated=truncated,
        challenges=tuple(challenges),
    )

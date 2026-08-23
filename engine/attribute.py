"""Tiered, deterministic attribution (spec FR-002/FR-004/FR-005, research R2/R3).

Tier A  — exact evidence (a UTR token equal to a settlement_utr) → razorpay_settlement.
Tier B  — scored combination of weak evidence (narration keywords, amount correlation,
          value-date proximity, brand+context) → highest-scoring rail, or UNKNOWN.
Tier C  — bounded set-sum: for razorpay-looking credits whose amount is not a single
          settlement net, try summing 2–3 settlement nets inside the value-date window
          (merge/carry-forward). Abstain on ambiguity or blow-up.

Precision-first (constitution IV): a Razorpay verdict may only outrank a competing
distinctive non-Razorpay narration keyword when it has a *hard* tie back to the recon
report (utr_exact / utr_suffix / amount_corr / setsum). Brand words alone never win —
that is exactly the decoy trap the benchmark sets.
"""

from __future__ import annotations

from itertools import combinations

from engine.evidence import (
    ReconIndex,
    extract_utr_tokens,
    narration_rail_signals,
    razorpay_signals,
)
from engine.models import BankCreditLine, EvidenceItem, Rail, RailAttribution, Tier

_HARD_RZP_SIGNALS = {"utr_exact", "utr_suffix", "setsum"}
# Amount/date agreement is CORROBORATING only, never sole proof (audit SERIOUS-2):
# a coincidental amount match must not auto-attribute Razorpay.
_RZP_COINCIDENTAL = {"amount_corr", "value_date_proximity"}
_SETSUM_MAX_TERMS = 3
_SETSUM_MAX_CANDIDATES = 40  # cap the candidate window; abstain rather than explode.


def _combine(items: list[EvidenceItem]) -> float:
    """Noisy-OR combination, capped. Independent signals reinforce; one strong dominates."""
    acc = 1.0
    for it in items:
        acc *= 1.0 - max(0.0, min(1.0, it.weight))
    return min(0.99, 1.0 - acc)


def _setsum_evidence(line: BankCreditLine, index: ReconIndex) -> list[EvidenceItem] | None:
    """Try to explain the credit as a sum of 2–3 settlement nets within the date window."""
    if not line.is_credit:
        return None
    target = line.amount_paise
    cands: list[tuple[str, int]] = []
    for sid, n in index.settlement_net.items():
        if n <= 0 or n >= target:
            continue
        d = index.settlement_date.get(sid)
        if d is not None and abs((line.value_date - d).days) <= 5:
            cands.append((sid, n))
    if not cands or len(cands) > _SETSUM_MAX_CANDIDATES:
        return None
    for k in range(2, _SETSUM_MAX_TERMS + 1):
        for combo in combinations(cands, k):
            if sum(n for _, n in combo) == target:
                sids = ", ".join(sid for sid, _ in combo)
                return [
                    EvidenceItem(
                        "setsum",
                        f"credit equals net sum of {k} settlements ({sids})",
                        0.55,
                    )
                ]
    return None


def attribute_line(line: BankCreditLine, index: ReconIndex, threshold: float) -> RailAttribution:
    rzp_ev = razorpay_signals(line, index)
    rzp_hard = any(e.signal in _HARD_RZP_SIGNALS for e in rzp_ev)
    non_rzp = narration_rail_signals(line)

    # Tier A: clean UTR exact match is decisive.
    if any(e.signal == "utr_exact" for e in rzp_ev):
        conf = _combine(rzp_ev)
        return RailAttribution(
            line.key, Rail.RAZORPAY_SETTLEMENT.value, conf, Tier.A.value, rzp_ev
        )

    # Tier C: no single-net/UTR tie yet, but the line looks Razorpay-ish → try set-sum.
    tier_used = Tier.B
    if not rzp_hard:
        setsum = _setsum_evidence(line, index)
        # Only apply set-sum when there is *some* Razorpay context, to avoid claiming
        # arbitrary credits that merely happen to sum. A competing gateway keyword blocks it.
        if setsum and (rzp_ev and not non_rzp):
            rzp_ev = rzp_ev + setsum
            rzp_hard = True
            tier_used = Tier.C

    # Build candidate rail scores.
    scores: dict[str, tuple[float, list[EvidenceItem], Tier]] = {}
    for rail, items in non_rzp.items():
        scores[rail.value] = (_combine(items), items, Tier.B)

    rzp_score = _combine(rzp_ev) if rzp_ev else 0.0
    # Precision guard: razorpay may only compete against a distinctive non-rzp keyword
    # when it has a hard recon tie.
    if non_rzp and not rzp_hard:
        rzp_score = 0.0
    # Coincidental-amount guard (audit SERIOUS-2): a Razorpay verdict needs at least one
    # substantive signal (UTR tie / set-sum / Razorpay identity token) — amount+date
    # agreement alone abstains rather than risk a false 'this is Razorpay's'.
    if not any(e.signal not in _RZP_COINCIDENTAL for e in rzp_ev):
        rzp_score = 0.0
    if rzp_score > 0.0:
        scores[Rail.RAZORPAY_SETTLEMENT.value] = (
            rzp_score,
            rzp_ev,
            tier_used if rzp_hard else Tier.B,
        )

    if not scores:
        return RailAttribution(
            line.key, Rail.UNKNOWN.value, 0.0, Tier.NONE.value, [], abstained=True
        )

    best_rail, (best_conf, best_ev, best_tier) = max(
        scores.items(), key=lambda kv: (kv[1][0], kv[0])
    )

    if best_conf < threshold:
        return RailAttribution(
            line.key, Rail.UNKNOWN.value, best_conf, Tier.NONE.value, best_ev, abstained=True
        )

    tier = best_tier if best_rail == Rail.RAZORPAY_SETTLEMENT.value else Tier.B
    return RailAttribution(line.key, best_rail, best_conf, tier.value, best_ev)


def attribute_all(
    lines: list[BankCreditLine], index: ReconIndex, threshold: float
) -> list[RailAttribution]:
    return [attribute_line(ln, index, threshold) for ln in lines]


def _extract_utrs(line: BankCreditLine) -> list[str]:  # re-export for tests
    return extract_utr_tokens(line.raw_text())

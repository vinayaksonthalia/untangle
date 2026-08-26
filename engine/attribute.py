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

from collections import defaultdict
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
_SETSUM_MAX_CANDIDATES = 200  # candidate pool size up to N=200 per Phase 2

_SIGNAL_CHANNELS = {
    "utr_exact": "identifier",
    "utr_suffix": "identifier",
    "settlement_ref": "identifier",
    "narration_brand_rzp": "narration",
    "ifsc_ratn": "narration",
    "amount_corr": "amount_time",
    "value_date_proximity": "amount_time",
    "setsum": "amount_time",
}


def _combine(items: list[EvidenceItem]) -> float:
    """Correlation-aware combination (G3 / spec FR-004).

    Evidence is grouped by independent channel (identifier, narration, amount/time).
    Correlated signals within a channel do NOT multiply as independent coin flips;
    instead, the dominant channel signal is augmented by bounded corroboration.
    Across independent channels, signals are combined using Noisy-OR.
    """
    if not items:
        return 0.0
    by_channel: dict[str, list[float]] = {}
    for it in items:
        ch = _SIGNAL_CHANNELS.get(it.signal)
        if ch is None:
            ch = "narration" if it.signal.startswith("narration_pattern:") else it.signal
        by_channel.setdefault(ch, []).append(max(0.0, min(1.0, it.weight)))

    channel_weights: list[float] = []
    for ch, weights in by_channel.items():
        if len(weights) == 1:
            channel_weights.append(weights[0])
        else:
            m = max(weights)
            boost = sum(w * 0.1 for w in weights if w != m)
            channel_weights.append(min(0.98, m + boost))

    acc = 1.0
    for w in channel_weights:
        acc *= 1.0 - w
    return min(0.99, 1.0 - acc)


def _setsum_evidence(line: BankCreditLine, index: ReconIndex) -> list[EvidenceItem] | None:
    """Try to explain the credit as a sum of 2–3 settlement nets within the date window.

    Enumerates ALL satisfying subsets (tolerance 0, candidate pool up to N=200).
    If >1 distinct subset of settlement_ids satisfies the amount, returns an EvidenceItem
    with signal 'multiple_satisfying_subsets' so the caller can abstain (G2/FR-003).
    """
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

    satisfying_subsets: list[tuple[str, ...]] = []
    seen: set[frozenset[str]] = set()

    # Check if any single settlement equals target in date window
    for sid in index.net_to_settlements.get(target, []):
        d = index.settlement_date.get(sid)
        if d is not None and abs((line.value_date - d).days) <= 5:
            subset = frozenset([sid])
            if subset not in seen:
                seen.add(subset)
                satisfying_subsets.append((sid,))

    val_to_sids: dict[int, list[str]] = defaultdict(list)
    for sid, n in cands:
        val_to_sids[n].append(sid)

    # 2-term sum (fast dictionary lookup)
    for i in range(len(cands)):
        sid_i, n_i = cands[i]
        rem = target - n_i
        if rem in val_to_sids:
            for sid_j in val_to_sids[rem]:
                if sid_j > sid_i:
                    sub = frozenset([sid_i, sid_j])
                    if sub not in seen:
                        seen.add(sub)
                        satisfying_subsets.append(tuple(sorted(sub)))
                        if len(satisfying_subsets) > 1:
                            break
        if len(satisfying_subsets) > 1:
            break

    # 3-term sum (fast dictionary lookup)
    if len(satisfying_subsets) <= 1:
        for i in range(len(cands)):
            sid_i, n_i = cands[i]
            for j in range(i + 1, len(cands)):
                sid_j, n_j = cands[j]
                rem = target - n_i - n_j
                if rem <= 0:
                    continue
                if rem in val_to_sids:
                    for sid_k in val_to_sids[rem]:
                        if sid_k > sid_j:
                            sub = frozenset([sid_i, sid_j, sid_k])
                            if sub not in seen:
                                seen.add(sub)
                                satisfying_subsets.append(tuple(sorted(sub)))
                                if len(satisfying_subsets) > 1:
                                    break
                if len(satisfying_subsets) > 1:
                    break
            if len(satisfying_subsets) > 1:
                break

    if len(satisfying_subsets) > 1:
        return [
            EvidenceItem(
                "multiple_satisfying_subsets",
                f"ambiguous set-sum: {len(satisfying_subsets)} distinct subsets sum to {target} paise",
                0.0,
            )
        ]

    if len(satisfying_subsets) == 1:
        subset_tuple = satisfying_subsets[0]
        # If it was a single settlement, that's already covered by amount_corr (not Tier C setsum)
        if len(subset_tuple) == 1:
            return None
        sids = ", ".join(subset_tuple)
        k = len(subset_tuple)
        return [
            EvidenceItem(
                "setsum",
                f"credit equals net sum of {k} settlements ({sids})",
                0.55,
            )
        ]

    return None


def attribute_line(line: BankCreditLine, index: ReconIndex, threshold: float) -> RailAttribution:
    non_rzp = narration_rail_signals(line)

    # FR-015: v1 attributes inbound CREDITS. A debit (bank charge / reversal / sweep-out) is
    # never a Razorpay settlement credit — credit-side signals (UTR ties, amount ties, Tier A)
    # must never fire on it, or a debit could be booked as a Razorpay credit and corrupt
    # reconciliation. A debit is classified only by a distinctive non-Razorpay narration
    # keyword (e.g. bank charges → unrelated), else abstained; it can never be razorpay_settlement.
    if not line.is_credit:
        d_scores = {rail.value: (_combine(items), items) for rail, items in non_rzp.items()}
        if not d_scores:
            return RailAttribution(line.key, Rail.UNKNOWN.value, 0.0, Tier.NONE.value, [], abstained=True)
        d_rail, (d_conf, d_ev) = max(d_scores.items(), key=lambda kv: (kv[1][0], kv[0]))
        if d_conf < threshold:
            return RailAttribution(line.key, Rail.UNKNOWN.value, d_conf, Tier.NONE.value, d_ev, abstained=True)
        return RailAttribution(line.key, d_rail, d_conf, Tier.B.value, d_ev)

    rzp_ev = razorpay_signals(line, index)
    rzp_hard = any(e.signal in _HARD_RZP_SIGNALS for e in rzp_ev)

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
        # If setsum is ambiguous (multiple satisfying subsets), must abstain per G2/FR-003
        if setsum and any(e.signal == "multiple_satisfying_subsets" for e in setsum):
            if not non_rzp:
                return RailAttribution(
                    line.key,
                    Rail.UNKNOWN.value,
                    0.0,
                    Tier.NONE.value,
                    rzp_ev + setsum,
                    abstained=True,
                )
        # Only apply set-sum when there is *some* Razorpay context, to avoid claiming
        # arbitrary credits that merely happen to sum. A competing gateway keyword blocks it.
        if setsum and not any(e.signal == "multiple_satisfying_subsets" for e in setsum) and (rzp_ev and not non_rzp):
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
    lines: list[BankCreditLine],
    index: ReconIndex,
    threshold: float,
    rules: list | None = None,
) -> list[RailAttribution]:
    base = [attribute_line(ln, index, threshold) for ln in lines]
    if not rules:
        return base
    from engine.rules import apply_approved_rules
    rule_attrs = apply_approved_rules(lines, rules)
    if not rule_attrs:
        return base
    # Human-approved rules resolve abstained exceptions (G5/FR-009)
    out: list[RailAttribution] = []
    for a in base:
        if a.abstained and a.line_key in rule_attrs:
            out.append(rule_attrs[a.line_key])
        else:
            out.append(a)
    return out


def _extract_utrs(line: BankCreditLine) -> list[str]:  # re-export for tests
    return extract_utr_tokens(line.raw_text())

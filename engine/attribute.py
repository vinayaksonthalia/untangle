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
# Signals that constitute a genuine TIE back to the settlement report — the only signals that
# may DECIDE a Razorpay verdict. amount_corr (credit equals an actual settlement net) is a real
# tie; a brand word, the Razorpay IFSC, a UTR-shaped-but-unlisted token (settlement_ref), and
# value_date_proximity are corroboration only and can never decide the verdict alone.
_RZP_TIE_SIGNALS = {"utr_exact", "utr_suffix", "setsum", "amount_corr"}
_SETSUM_MAX_TERMS = 3
_SETSUM_MAX_CANDIDATES = 200  # candidate pool size up to N=200 per Phase 2

_SIGNAL_CHANNELS = {
    "utr_exact": "identifier",
    "utr_suffix": "identifier",
    "utr_suffix_weak": "identifier",
    "settlement_ref": "identifier",
    "narration_brand_rzp": "narration",
    "ifsc_ratn": "narration",
    "amount_corr": "amount_time",
    "amount_corr_multi": "amount_time",
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
    for _ch, weights in by_channel.items():
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
    # PROOF-GATE INVARIANT: a Razorpay verdict requires at least one genuine tie back to the
    # settlement report — a UTR identifier tie (utr_exact/utr_suffix), a bounded set-sum, or an
    # amount that equals an actual settlement net (amount_corr). Signals that merely *resemble*
    # Razorpay are corroboration only and can NEVER decide the verdict on their own:
    #   • narration brand words / the Razorpay IFSC — resemblance, not a tie;
    #   • settlement_ref — a UTR-SHAPED token that is, by construction, NOT in the settlement
    #     report, so it proves nothing; brand + such a token is exactly the decoy trap.
    # value_date_proximity alone is not a tie either. Without a tie the line abstains.
    if not any(e.signal in _RZP_TIE_SIGNALS for e in rzp_ev):
        rzp_score = 0.0
    if rzp_score > 0.0:
        scores[Rail.RAZORPAY_SETTLEMENT.value] = (
            rzp_score,
            rzp_ev,
            tier_used if rzp_hard else Tier.B,
        )

    if not scores:
        # Proof-gate abstention: razorpay evidence may have been zeroed for lacking a tie. Keep
        # that evidence on the abstained line so the exception surfaces "razorpay-leaning but no
        # settlement tie — review against the settlement report", not "no distinctive signal".
        return RailAttribution(
            line.key, Rail.UNKNOWN.value, 0.0, Tier.NONE.value, rzp_ev, abstained=True
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


_SPLIT_MAX_LEGS = 3
_SPLIT_DRIFT_PAISE = 100      # ±₹1 rounding-drift tolerance (matches reconcile)
_SPLIT_DATE_WINDOW = 5
_SPLIT_MAX_CANDIDATES = 60    # per settlement; skip (abstain) if the eligible pool is larger


_RZP_LEANING_SIGNALS = {
    "narration_brand_rzp", "ifsc_ratn", "settlement_ref", "utr_suffix", "utr_suffix_weak",
}
# A subset may only be reconstructed if at least one leg carries a STRONG Razorpay-origin signal:
# the Razorpay RBL settlement-account IFSC (RATN0000088, Razorpay-specific, not a generic bank) or
# a corroborated UTR suffix (a real, verified match to a settlement_utr). settlement_ref is NOT
# strong — it is a UTR-shaped token that is, by construction, absent from the settlement report, so
# it is resemblance (the proof-gate's own ruling), never proof. A brand word and a weak
# (uncorroborated) suffix are likewise not strong. Coincidental sums cannot fabricate a verdict.
_STRONG_RZP_SIGNALS = {"ifsc_ratn", "utr_suffix"}


def _all_sum_subsets(
    items: list[BankCreditLine], target: int, tol: int, max_legs: int
) -> list[tuple[BankCreditLine, ...]]:
    """Every DISTINCT subset of 2..max_legs credits whose amounts sum to `target` (±tol)."""
    out: list[tuple[BankCreditLine, ...]] = []
    seen: set[frozenset[str]] = set()
    for k in range(2, max_legs + 1):
        for combo in combinations(items, k):
            if abs(sum(c.amount_paise for c in combo) - target) <= tol:
                fk = frozenset(c.key for c in combo)
                if fk not in seen:
                    seen.add(fk)
                    out.append(combo)
    return out


_SPLIT_CONFIDENCE = 0.9


def reconstruct_splits(
    lines: list[BankCreditLine],
    index: ReconIndex,
    attrs: list[RailAttribution],
    threshold: float,
) -> list[RailAttribution]:
    """Recover split-settlement legs the *provable* way (FR-016): a Razorpay settlement paid out
    across 2–3 bank credits leaves legs whose per-leg UTR is absent from the recon report, so each
    leg abstains. The legs' amounts sum to a real settlement net within the value-date window — a
    genuine tie back to the settlement report. A leg is lifted to razorpay_settlement (Tier C) only
    when ALL of these hold (precision-first; a coincidental sum must never fabricate a verdict):
      • it already abstained and carries NO distinctive competing rail keyword;
      • it carries a Razorpay-origin signal, and its subset has at least one STRONG one (the
        Razorpay-specific IFSC RATN, a settlement_ref, or a corroborated UTR suffix) — a brand
        word or an uncorroborated suffix alone can never turn a coincidental sum into a verdict;
      • its subset is the ONE match for a dated settlement net, and none of its credits appear in
        ANY other matching subset (global conflict analysis, not greedy per-settlement uniqueness).
    Any ambiguity — a settlement with >1 matching subset, or a credit shared across subsets —
    abstains the whole affected group.
    """
    sig_by_key: dict[str, set[str]] = {}
    # The reconstruction's confidence is fixed; if the runtime cutoff is stricter than that, split
    # legs must abstain like any other sub-threshold verdict — the threshold governs ALL money calls.
    if _SPLIT_CONFIDENCE < threshold:
        return attrs
    candidates: list[BankCreditLine] = []
    for ln, a in zip(lines, attrs, strict=True):
        if not (a.abstained and ln.is_credit and ln.amount_paise > 0 and not narration_rail_signals(ln)):
            continue
        sigs = {e.signal for e in razorpay_signals(ln, index)}
        if _RZP_LEANING_SIGNALS & sigs:
            candidates.append(ln)
            sig_by_key[ln.key] = sigs
    if len(candidates) < 2:
        return attrs

    # Phase 1: collect ALL (settlement, subset) matches over the FULL candidate pool. Settlements
    # without a verified settled date are skipped (a missing date is not an unbounded window). A
    # credit eligible for an OVERSIZED pool (one we decline to enumerate) is poisoned: it may never
    # be assigned to any settlement, so the cap can never make a conflict falsely look unique.
    matches: list[tuple[str, tuple[BankCreditLine, ...]]] = []
    poisoned: set[str] = set()
    for sid in sorted(index.settlement_net):
        net = index.settlement_net[sid]
        sdate = index.settlement_date.get(sid)
        if net <= 0 or sdate is None:
            continue
        elig = [
            c for c in candidates
            if c.amount_paise < net and abs((c.value_date - sdate).days) <= _SPLIT_DATE_WINDOW
        ]
        if len(elig) < 2:
            continue
        if len(elig) > _SPLIT_MAX_CANDIDATES:
            poisoned.update(c.key for c in elig)
            continue
        for sub in _all_sum_subsets(elig, net, _SPLIT_DRIFT_PAISE, _SPLIT_MAX_LEGS):
            matches.append((sid, sub))

    # Phase 2: global conflict/ambiguity analysis. Assign a subset only when its settlement has
    # exactly one matching subset, every credit in it appears in no other matching subset, none is
    # poisoned, AND at least one leg carries a STRONG Razorpay-origin signal (a coincidental sum of
    # brand-only credits must never fabricate a verdict).
    from collections import Counter
    per_settlement = Counter(sid for sid, _ in matches)
    per_key = Counter(c.key for _, sub in matches for c in sub)
    assigned: dict[str, tuple[str, int, int]] = {}  # line.key -> (sid, n_legs, group_residual_paise)
    for sid, sub in matches:
        if per_settlement[sid] != 1:
            continue
        if any(per_key[c.key] != 1 or c.key in poisoned for c in sub):
            continue
        if not any(_STRONG_RZP_SIGNALS & sig_by_key[c.key] for c in sub):
            continue
        residual = sum(c.amount_paise for c in sub) - index.settlement_net[sid]
        for c in sub:
            assigned[c.key] = (sid, len(sub), residual)

    if not assigned:
        return attrs
    out: list[RailAttribution] = []
    for ln, a in zip(lines, attrs, strict=True):
        if ln.key in assigned:
            sid, k, residual = assigned[ln.key]
            balance = "exactly" if residual == 0 else f"within {abs(residual)} paise of"
            ev = [EvidenceItem(
                "split_reconstruction",
                f"1 of {k} bank legs whose amounts uniquely sum to {balance} the settlement net for {sid}",
                _SPLIT_CONFIDENCE,
            )]
            out.append(RailAttribution(
                ln.key, Rail.RAZORPAY_SETTLEMENT.value, _SPLIT_CONFIDENCE, Tier.C.value, ev, abstained=False
            ))
        else:
            out.append(a)
    return out


def attribute_all(
    lines: list[BankCreditLine],
    index: ReconIndex,
    threshold: float,
    rules: list | None = None,
) -> list[RailAttribution]:
    base = [attribute_line(ln, index, threshold) for ln in lines]
    base = reconstruct_splits(lines, index, base, threshold)
    if not rules:
        return base
    from engine.rules import apply_approved_rules
    rule_attrs = apply_approved_rules(lines, rules)
    if not rule_attrs:
        return base
    # Human-approved rules resolve abstained exceptions (G5/FR-009). One special case:
    # a rule *conflict* (contradictory human approvals) is an explicit abstention that must
    # OVERRIDE a soft base verdict (Tier B/C/LLM) — humans disagreeing outweighs a weak guess.
    # It never overrides Tier A: a clean UTR-exact identifier tie is machine fact, not opinion.
    out: list[RailAttribution] = []
    for a in base:
        ra = rule_attrs.get(a.line_key)
        if ra is None:
            out.append(a)
            continue
        is_conflict = any(e.signal == "rule_conflict" for e in ra.evidence)
        if is_conflict:
            out.append(a if a.tier == Tier.A.value else ra)
        elif a.abstained:
            out.append(ra)
        else:
            out.append(a)
    return out


def _extract_utrs(line: BankCreditLine) -> list[str]:  # re-export for tests
    return extract_utr_tokens(line.raw_text())

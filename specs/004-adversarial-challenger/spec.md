# Feature Specification: Adversarial Challenger & Proof-Margin Gate

**Feature**: 004-adversarial-challenger
**Status**: Draft
**Created**: 2026-08-27

## Why (problem & taste)

untangle already refuses to call a credit "Razorpay's" without a genuine tie back to the settlement
report (the proof-gate). But acceptance today asks only *"can I find a valid tie?"* A finance
controller that is genuinely intelligent must ask the harder question: *"can I **disprove** this
attribution?"* — and abstain when a competing explanation is nearly as strong, even if a valid tie
exists. This is the behaviour that separates a smart agent from a confident matcher: it knows when
**not** to act, and it can quantify *how close* it came to being wrong.

## What (scope)

Before any **machine** Razorpay attribution is accepted, actively generate a bounded set of
counterfactual ("challenger") explanations, score them with the *same* scoring function used for the
candidate, and compute a **proof margin**:

```
proof_margin = best_valid_rzp_score − best_competing_score
```

Accept the Razorpay verdict only when the existing proof-gate passes **and**
`proof_margin ≥ margin_threshold`, where `margin_threshold` is set by **conformal calibration** on the
sealed adversarial holdout to guarantee a precision target. Otherwise the line **abstains**, carrying
the strongest competing explanation as its reason.

The margin can **only** turn a Razorpay verdict into an abstention. It never creates, upgrades, or
alters a non-Razorpay verdict. With `margin_threshold = 0.0` (default) behaviour is identical to today.

### In scope
- A pure `engine/challenger.py` with bounded, deterministic challenger operators (evidence ablations +
  competing-rail + set-sum repartition + same-amount alternatives).
- A proof-margin gate wired into **both** machine Razorpay acceptance paths: `attribute_line` and
  split reconstruction (`reconstruct_splits`).
- Conformal margin calibration in `eval/calibration.py` (Clopper–Pearson upper bound, Bonferroni over
  the threshold grid), reporting precision, precision lower bound, coverage, and recall separately.
- Surfacing: optional `proof_margin` + `competing_explanation` on the attribution and proof packet; a
  structured exception message on margin abstentions.

### Out of scope
- Human-approved rules (explicit exception resolution, not machine attribution).
- Any change to reconciliation, GST, or the ledger feature.
- Global/joint reconciliation (that is Feature #1, a later roadmap item).

## User scenarios

1. **A decoy nearly matches.** A credit has a valid amount tie to one Razorpay settlement, but a
   competing gateway's distinctive narration scores almost as high. Margin is small → untangle
   abstains with "strongest alternative: <gateway> (score)", instead of booking Razorpay. *A weaker
   agent books the wrong rail here.*
2. **A clean UTR.** An exact `utr_exact` tie with no plausible competitor → large margin → accepted,
   with the margin and the (weak) strongest challenger recorded in the proof packet.
3. **Ambiguous set-sum.** A credit equals two different provable subsets of settlement nets → the
   repartition operator forces margin 0 → abstain (already the Tier C contract; now audited).
4. **Nothing changes for non-Razorpay.** UPI/COD/other-gateway/unrelated verdicts are byte-identical.

## Success criteria

- **SC-001** With `margin_threshold = 0.0`, every headline metric is byte-identical to pre-feature
  (additivity): precision 1.000, recall 0.91, reconciled count, fee-GST.
- **SC-002** Precision monotonicity: for any batch, the set of Razorpay predictions under the gate is a
  **subset** of the pre-gate predictions (so precision can never drop, and false-positives can only
  decrease).
- **SC-003** Calibration certifies a threshold with **Razorpay precision = 1.000** on the sealed
  holdout and **recall ≥ 0.90** (≤ 0.01 drop from baseline), or fails closed (feature stays disabled).
- **SC-004** Deterministic: same inputs → identical margins, challenger order, and verdicts.
- **SC-005** Every margin abstention carries a structured `competing_explanation`; every acceptance's
  proof packet carries its `proof_margin`.
- **SC-006** Bounded work: ≤ 16 challenges per line; set-sum repartition capped; truncation ⇒ abstain.

## Key entities
- **CompetingExplanation** — `{operator, rail, score, detail, removed_signals}`.
- **ChallengerResult** — `{rzp_score, competing_score, proof_margin, strongest, challenges_evaluated, truncated}`.
- **MarginCalibration** — `{threshold, precision, precision_lower_bound, candidate_coverage, overall_coverage, razorpay_recall, accepted, errors}`.

## Constitution check
- **Precision-first / abstain over guess**: the gate only ever *adds* abstentions on the strongest
  evidence of ambiguity. ✓
- **Deterministic, stdlib-only**: bounded search + exact arithmetic; `math.comb` for the bound. ✓
- **Additive**: default threshold 0.0 = no change; property test locks headline metrics. ✓
- **Honest metrics**: coverage is never called precision; calibration reports a finite-sample lower
  bound and its distribution-shift caveat. ✓
- **Read-only toward money**: no writes, no feedback into `ReconIndex`/reconciliation. ✓

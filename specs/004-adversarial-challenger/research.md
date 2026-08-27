# Research: Adversarial Challenger & Proof-Margin Gate

Decisions resolving the design axes. Each is precision-first, deterministic, and grounded in the
existing `engine/attribute.py` control flow.

## D1 — Margin definition (use the existing scoring, not an invented probability)
`best_valid_rzp_score = _combine(rzp_ev)` (nonzero only after the `_RZP_TIE_SIGNALS` proof-gate passes).
`best_competing_score = max(0.0, max competing non-Razorpay rail `_combine`, max challenger score)`.
`proof_margin = best_valid_rzp_score − best_competing_score`. Never `1 − rzp_score`. Scores come only
from `_combine`, passed in as a callable to avoid a circular import and to guarantee identical scoring.

## D2 — Gate placement & direction (abstain-only)
Compute the margin after `scores` is built and the winner is Razorpay, before the winning return. If
`proof_margin < margin_threshold` → return UNKNOWN/abstained, preserving `confidence = rzp_score` and
the Razorpay evidence plus the strongest competing explanation. The margin can **only** demote a
Razorpay verdict; non-Razorpay decisions are untouched. Tier A's early `utr_exact` return is refactored
so it too reaches the gate (its confidence bypass is preserved; only the margin may abstain it).

## D3 — Two machine acceptance paths (caught during design)
Split reconstruction (`reconstruct_splits`) is a *second* machine path that accepts Razorpay. The gate
must apply there too: globally-unique subset → competing 0.0, margin ≈ 0.9; any alternative/oversized
pool/shared credit already abstains. `split_reconstruction` is added to the accepted proof-signal set.

## D4 — Challenger operators (bounded, deterministic)
Nine operators, hard cap 16/line, fixed order, deterministic sort `(operator, rail, detail)`, overflow
⇒ `truncated=True` ⇒ abstain. Ablations remove a signal group and re-score the *remaining* rzp evidence:
`observed_competing_rail`, `drop_exact_identifier` (utr_exact/suffix/suffix_weak),
`drop_suffix`, `drop_amount_tie` (amount_corr/_multi), `same_amount_alternative` (warning, ±5 days),
`drop_setsum`, `repartition_setsum` (2–3 term subsets, ≤200 candidates; another distinct subset ⇒ margin
0), `drop_time_proximity`, `unlinked_rzp` (strip all ties → brand/IFSC/settlement_ref/date remain).
No operator mutates `ReconIndex`, the line, or reconciliation state. "Shift the window" = removing
`value_date_proximity`, never fabricating a bank date.

## D5 — Conformal calibration (finite-sample precision guarantee)
One global threshold initially (report per-tier; per-tier thresholds only once each tier has the sample
to certify). Procedure on the sealed holdout: record every would-be Razorpay candidate's `proof_margin`,
tier, correctness; evaluate the predeclared grid `0.000..1.000` step `0.005` (201 points); at each, with
`n` accepted and `k` wrong, compute a one-sided **Clopper–Pearson** upper bound `U(k,n,alpha/201)` on the
error rate (Bonferroni over the 201 predeclared thresholds ⇒ selection itself is covered); certify where
`1−U ≥ target_precision`; also require `razorpay_recall ≥ baseline − 0.01` and `≥ 0.90`; pick the
certified threshold with max candidate coverage (tie-break: lower threshold); if none passes, **fail
closed** (feature stays disabled). Report precision, precision lower bound, candidate coverage, overall
coverage, recall, recall delta, and per-tier breakdown — coverage is never labelled precision. Caveat:
the guarantee assumes the sealed holdout is exchangeable with deployment; an adversarial set alone cannot
guarantee production precision under arbitrary shift (stated honestly).

## D6 — Data model (additive, defaulted)
Append to `RailAttribution`: `proof_margin: float | None = None`, `competing_explanation: dict | None =
None`. Old constructors keep working. Proof packet carries the margin for accepted lines and the
competing explanation for margin abstentions. Dashboard exception text is generated from the structured
fields, not stuffed into a free-form `EvidenceItem.detail`.

## D7 — Precision monotonicity as the safety invariant
Because the gate only removes Razorpay predictions, the post-gate Razorpay set ⊆ pre-gate set. A property
test asserts `new_rzp_keys ⊆ baseline_rzp_keys` and `new_false_positive_keys ⊆ baseline_fp_keys` on every
generated batch — so precision cannot drop and false-positives can only fall. This is the core guardrail.

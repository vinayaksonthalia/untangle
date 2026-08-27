---
description: "Task list for Adversarial Challenger & Proof-Margin Gate (Feature 004)"
---

# Tasks: Adversarial Challenger & Proof-Margin Gate

**Tests**: INCLUDED — money path; constitution mandates test-first / property-based.
Stories: US1 proof-margin gate (P1), US2 challenger operators (P2), US3 conformal calibration (P3).

## Phase 1: Setup
- [ ] T001 Create `engine/challenger.py` with module docstring, `CompetingExplanation` and
  `ChallengerResult` frozen dataclasses, and a `challenge_razorpay(...)` stub returning a zero-margin
  result (competing 0.0, margin = rzp_score). Import models; no new deps.
- [ ] T002 [P] Create `tests/unit/test_challenger.py` + `tests/property/test_challenger_additive.py`
  with imports and crafted-batch helpers.

## Phase 2: Foundational (blocks stories)
- [ ] T003 Add optional defaulted fields to `RailAttribution` in `engine/models.py`:
  `proof_margin: float | None = None`, `competing_explanation: dict | None = None`.
- [ ] T004 **Additivity + monotonicity property test FIRST**: at `margin_threshold=0.0`, headline
  metrics byte-identical (SC-001); at any threshold, post-gate Razorpay set ⊆ baseline set and
  false-positives ⊆ baseline (SC-002); determinism + empty inputs safe.
- [ ] T005 Add `margin_threshold` keyword (default 0.0) to `attribute_line` and `attribute_all`;
  thread from `engine/config.py`.

## Phase 3: US1 — Proof-margin gate (P1) 🎯 MVP
- [ ] T006 [P][US1] Unit tests: Razorpay winner with small margin abstains carrying strongest
  competitor; large margin accepts with `proof_margin` set; non-Razorpay verdicts unchanged.
- [ ] T007 [US1] Refactor the Tier A `utr_exact` early return so it reaches the gate (preserve its
  confidence bypass); insert the gate after `scores` is built and the winner is Razorpay.
- [ ] T008 [US1] Apply the same gate to the split-reconstruction acceptance path; add
  `split_reconstruction` to the accepted proof-signal set.

## Phase 4: US2 — Challenger operators (P2)
- [ ] T009 [P][US2] Unit tests per operator (observed-competing, drop_exact_identifier, drop_suffix,
  drop_amount_tie, same_amount_alternative-is-warning, drop_setsum, repartition_setsum forces margin 0,
  overflow abstains, drop_time_proximity, unlinked_rzp remains competing-only, order+cap deterministic).
- [ ] T010 [US2] Implement the nine operators in `challenger.py`: bounded (≤16), fixed order,
  deterministic sort, truncation ⇒ abstain; repartition capped at 200 subsets. No state mutation.

## Phase 5: US3 — Conformal calibration (P3)
- [ ] T011 [P][US3] Calibration tests: zero-accepted, zero-errors, one-error, insufficient sample,
  grid tie-break (lower threshold), Bonferroni correction, and no-feasible-threshold fail-closed.
- [ ] T012 [US3] Implement `MarginCalibration` + `calibrate_proof_margin` in `eval/calibration.py`
  (Clopper–Pearson upper bound via `math.comb` + binary search on the binomial CDF; recall guard;
  fail-closed) and honest reporting (precision, lower bound, coverage×2, recall, delta, per-tier).
- [ ] T013 [US3] Wire calibration into the sealed-eval flow to emit the certified threshold + report;
  set `margin_threshold` in `engine/config.py` from the certified value.

## Phase 6: Polish
- [ ] T014 [P] Surface: proof-packet `proof_margin` for accepted lines; structured
  `competing_explanation` on margin abstentions; dashboard exception text from structured fields
  (new reason label if needed). Regenerate `ui/dashboard.html`.
- [ ] T015 [P] Docs: README metrics + a short "adversarial challenger / proof margin" section; landing
  proof band if a metric changes; `docs/EXCEPTION_TAXONOMY.md`.
- [ ] T016 Full suite green (ruff, bandit, pytest incl. new unit+property+calibration); run the metric
  sweep and confirm precision 1.000 / recall ≥ 0.90 at the certified threshold; log any real defect in
  `INCIDENTS.md`.

## Dependencies
Phase 1 → 2 (models + property guardrail + threshold plumbing) → US1 (gate MVP) → US2 (operators) →
US3 (calibration) → polish. The additivity+monotonicity property test (T004) guards every later task.

## MVP
US1 alone (the gate, with observed-competing-rail only) is a shippable increment — it already abstains
on the strongest real competitor. US2 deepens the counterfactual search; US3 makes the threshold a
calibrated guarantee.

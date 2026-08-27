# Implementation Plan: Adversarial Challenger & Proof-Margin Gate

**Branch**: `feat/adversarial-challenger` · **Spec**: [spec.md](spec.md) · **Research**: [research.md](research.md)

## Technical context
- Language: Python ≥3.12, stdlib-only runtime (adds nothing; `math.comb` for the bound).
- Touch points: new `engine/challenger.py`; edits to `engine/attribute.py` (gate + Tier A refactor),
  `engine/reconstruct.py`/split path (second gate), `engine/models.py` (2 optional fields),
  `eval/calibration.py` (margin calibration + reporting), `engine/proof.py` + `ui/dashboard.py`
  (surfacing), `engine/config.py` (the calibrated `margin_threshold`, default 0.0).
- Determinism & additivity are hard gates (constitution). Property test locks headline metrics with
  threshold 0.0 and locks precision-monotonicity at any threshold.

## Approach (thin, well-tested, precision-first)
1. **Foundational**: `challenger.py` pure functions + `ChallengerResult`/`CompetingExplanation`; a
   property test that the gate at threshold 0.0 changes nothing, and precision-monotonicity at any
   threshold. These pass by construction (abstain-only gate).
2. **Operators**: implement the nine operators over real evidence signals + `ReconIndex`, bounded and
   deterministic; unit test each.
3. **Wiring**: refactor Tier A early-return; insert the gate in `attribute_line`; insert the same gate
   in the split-reconstruction acceptance path. `margin_threshold` keyword, default 0.0.
4. **Calibration**: `calibrate_proof_margin` (Clopper–Pearson + Bonferroni + recall guard + fail-closed)
   and honest reporting; wire into the sealed-eval flow to emit the certified threshold + report.
5. **Surfacing**: proof-packet margin, structured competing-explanation on abstentions, dashboard text.
6. **Enable**: set `margin_threshold` in config from the certified value; full docs + metric sweep.

## Constitution gates
- Precision-first ✓ (abstain-only). Deterministic ✓. Additive ✓ (default 0.0 + property test).
- Honest metrics ✓ (coverage ≠ precision; finite-sample bound + shift caveat).
- Read-only ✓ (no feedback into recon).

## Risks
- Tier A refactor must not change accepted-verdict confidence/behaviour except via the new gate.
- Calibration sample size per tier — start global, report per-tier, certify per-tier only when able.
- Recall drop from over-aggressive abstention — bounded by the ≤0.01 guard; if a threshold can't meet
  both precision and recall, fail closed and keep the feature disabled.

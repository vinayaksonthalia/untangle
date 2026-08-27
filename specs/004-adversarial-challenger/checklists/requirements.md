# Specification Quality Checklist: Adversarial Challenger & Proof-Margin Gate

## Content Quality
- [x] Focused on user value (knows when NOT to act) and the panel-defensible "where's the AI" answer
- [x] Mandatory sections completed

## Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers
- [x] Requirements testable (SC-001..006, precision-monotonicity, calibration fail-closed)
- [x] Success criteria measurable and honest (coverage ≠ precision; finite-sample bound + shift caveat)
- [x] Scope bounded (machine attribution only; global solver deferred to Feature #1)
- [x] Additivity + determinism + read-only invariants stated

## Feature Readiness
- [x] Additive by construction (default threshold 0.0); property test locks headline metrics
- [x] Precision can never drop (monotone subset); recall guarded (≤0.01) with fail-closed calibration
- [x] Two machine acceptance paths covered (attribute_line + split reconstruction)

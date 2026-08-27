---
description: "Task list for Active Recovery Controller (Feature 005)"
---

# Tasks: Active Recovery Controller

**Tests**: INCLUDED — constitution mandates test-first where marked + a property-based additivity test.
Stories: US1 diagnosis & hypotheses (Phase 1), US2 actions & ranking (Phase 2), US3 recovery trail
(Phase 3), US4 wiring & surfacing (Phase 4).

## Phase 0: Spec-kit trail
- [ ] T001 Create the spec-kit trail in `specs/005-active-recovery-controller/`: `spec.md`,
  `plan.md`, `research.md`, `data-model.md`, `contracts/recovery.md`,
  `checklists/requirements.md`, `tasks.md`. Derived from `PHASE_PLAN.md`.

## Phase 1: US1 — Diagnosis & hypotheses (P1) 🎯
- [ ] T002 [test-first] Create `tests/unit/test_recovery.py` with unit tests for `diagnose()`:
  for each abstention reason (brand-no-tie, weak-suffix, ambiguous set-sum, unknown-sender, ledger
  exception) assert the expected `blocking_reason` and hypothesis rail/weight.
- [ ] T003 Create `engine/recovery.py` with `Hypothesis`, `RecoveryAction`, `RecoveryPlan` frozen
  dataclasses and `diagnose(line, attribution, index, exception) -> list[Hypothesis]`.
- [ ] T004 Acceptance: deterministic; only reads inputs; hypotheses' weights come from existing
  evidence scores; tests pass.

## Phase 2: US2 — Actions & ranking (P2) 🎯
- [ ] T005 [test-first] Unit tests: crafted batches of unresolved credits → expected grouped,
  ranked `RecoveryAction`s (correct `resolves` grouping, `recoverable_paise` = summed amounts,
  `gain_per_cost` ordering, deterministic tie-break, top-N cap with note).
- [ ] T006 Implement `build_recovery_plan(lines, attributions, index, exceptions, *,
  max_actions=20) -> RecoveryPlan`: diagnose per unresolved credit, map to actions, group by
  identical action, compute metrics, rank, cap, fill summary.
- [ ] T007 Acceptance: pure; no double-counting in `recoverable_if_actioned_paise`; every human
  string frames amounts as "up to … if confirmed".

## Phase 3: US3 — Recovery trail & rerun diff (P3)
- [ ] T008 [test-first] Tests: `resolve_delta(before, after)` given two report dicts returns
  newly resolved line_keys and recovered paise. Deterministic; safe on identical inputs.
- [ ] T009 Implement `resolve_delta(before_report, after_report) -> dict`.
- [ ] T010 Acceptance: additive, read-only, deterministic.

## Phase 4: US4 — Wiring & surfacing (P4)
- [ ] T011 Wire into `build_report`: after exceptions, call `build_recovery_plan(...)` and
  attach as `recovery_plan` in the report. Never alters attributions/reconciliation/metrics.
- [ ] T012 [property test] `tests/property/test_recovery_additive.py`: headline metrics
  byte-identical with/without the recovery step; determinism; empty/edge inputs safe.
- [ ] T013 Dashboard: "Recovery plan" panel in `ui/dashboard.py` — ranked actions, each showing
  the action, what it would resolve, and "up to ₹X recoverable if confirmed". Regenerate
  `ui/dashboard.html`. Add to CLI/JSON report surface.

## Phase 5: Polish
- [ ] T014 [P] Docs: README bullet, `docs/EXCEPTION_TAXONOMY.md` cross-links, spec quickstart.
- [ ] T015 Full suite green (ruff, pytest incl. new unit + property); metric sweep confirms
  precision 1.000 / recall unchanged; log any defect in `INCIDENTS.md`.

## Dependencies
Phase 0 → Phase 1 (diagnosis) → Phase 2 (actions & ranking) → Phase 3 (rerun diff) →
Phase 4 (wiring & surfacing & additivity property test) → Phase 5 (docs & polish).

## MVP
Phase 1 + Phase 2 alone (diagnosis + ranked recovery plan) is a shippable increment — it already
turns abstention into ranked, actionable recovery recommendations. Phase 3 adds the rerun-diff
trail; Phase 4 wires it all together and proves additivity.

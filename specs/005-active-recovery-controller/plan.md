# Implementation Plan: Active Recovery Controller

**Branch**: `feat/active-recovery-controller` · **Spec**: [spec.md](spec.md) · **Research**: [research.md](research.md)

## Technical context
- Language: Python ≥3.12, stdlib-only runtime (adds nothing).
- Touch points: new `engine/recovery.py`; edits to `engine/cli.py` (`build_report`),
  `ui/dashboard.py` (recovery panel), `engine/models.py` (`RunReport.to_dict` — new section).
- The recovery controller is a **post-pipeline read-only pass** — it runs after exceptions are
  built and attaches a `RecoveryPlan` to the report. It never alters attributions, reconciliations,
  fee-GST, or headline metrics.
- Additivity + determinism are hard gates (constitution). Property test locks headline metrics.

## Approach (thin, additive, test-first)
1. **Phase 0 (spec-kit trail):** produce the spec-kit trail (`spec.md`, `plan.md`, `research.md`,
   `data-model.md`, `contracts/`, `checklists/requirements.md`, `tasks.md`) in
   `specs/005-active-recovery-controller/`.
2. **Phase 1 (diagnosis):** `engine/recovery.py` with data model + `diagnose()` — test-first.
3. **Phase 2 (actions & ranking):** `build_recovery_plan()` — test-first, grouped, ranked.
4. **Phase 3 (rerun diff):** `resolve_delta()` — test-first.
5. **Phase 4 (wiring & surfacing):** wire into `build_report`, dashboard panel, property test.
6. **Phase 5 (docs & polish):** docs sweep, full suite green, metric sweep.

## Constitution gates
- Additive ✓ (post-pipeline pass; property test). Deterministic ✓. Read-only ✓.
- Precision-first ✓ (recommends, never asserts). Honest ✓ (amounts are "up to … if confirmed").
- Stdlib-only ✓ (no new deps). No LLM ✓.

## Risks
- `build_recovery_plan` must not accidentally mutate inputs — frozen dataclasses and defensive
  copies mitigate this.
- `recoverable_if_actioned_paise` must not double-count credits resolvable by multiple actions —
  use a set union over `resolves` keys.
- Dashboard HTML generation must not break existing sections — the recovery panel is appended,
  never inserted into existing content.

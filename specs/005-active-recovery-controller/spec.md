# Feature Specification: Active Recovery Controller

**Feature**: 005-active-recovery-controller
**Status**: Draft
**Created**: 2026-08-28

## Why (problem & taste)

untangle already abstains rather than guess: unresolved bank credits go to an exception queue with a
`reason_code` and a `suggested_action` (see `engine/models.py:ExceptionRecord`, `engine/exceptions.py`).
But those suggestions are static, per-credit, and unranked. A finance controller that is genuinely
intelligent must not only say "I can't prove this" — it must say *"here is the single highest-value
thing to do next, and it would resolve ₹X across N credits."*

The Active Recovery Controller turns abstention into an intelligent, ranked recovery plan.

## What (scope)

For every unresolved credit:
1. **Diagnose** why it couldn't be proven (derive a `blocking_reason` from existing evidence +
   exception `reason_code`).
2. **Hypothesize** which rail it might be, with weight from the existing `_combine` scores.
3. **Map** each blocking reason to a concrete `RecoveryAction` from the fixed taxonomy (§3 of
   PHASE_PLAN.md).
4. **Group** credits that the *same* action (same type + params) would resolve into a single action.
5. **Rank** actions by `gain_per_cost` = `recoverable_paise / cost` (descending; stable tie-break).
6. **Surface** the ranked plan in the report, dashboard, and CLI.

Additionally, `resolve_delta(before, after)` compares two report dicts (a run, then a rerun with
better inputs) and returns the set of newly resolved credits and recovered paise.

### In scope
- A pure `engine/recovery.py` with `Hypothesis`, `RecoveryAction`, `RecoveryPlan` frozen dataclasses.
- `diagnose(line, attribution, index, exception) -> list[Hypothesis]` — per-credit diagnosis.
- `build_recovery_plan(lines, attributions, index, exceptions, *, max_actions=20) -> RecoveryPlan`.
- `resolve_delta(before_report, after_report) -> dict` — the recovery trail step.
- Wiring into `build_report` as a new top-level `recovery_plan` section.
- A dashboard panel showing the ranked next-best actions.
- A property test locking headline metric additivity.

### Out of scope
- An interactive server-side loop / uploading follow-up files through the UI (the rerun is just
  re-running the existing pipeline with better inputs).
- Anything probabilistic that an LLM would decide.
- Any change to attribution, reconciliation, GST, or the headline metrics.

## User scenarios

1. **Mangled UTRs.** Three Razorpay credits have destroyed UTR prefixes. untangle abstains on all 3.
   The Recovery Plan says: "Export the Razorpay settlement report for Jan 3–5 — would resolve 3
   credits, up to ₹Y, if the settlement rows confirm the tie." The merchant exports, re-runs, and
   `resolve_delta` shows all 3 newly reconciled with recovered paise.

2. **Ambiguous set-sum.** A credit equals two distinct settlement subsets. The Recovery Plan says:
   "Provide settlement IDs for ₹X on date D — would resolve 1 credit if confirmed."

3. **Unknown sender.** A credit with no distinctive signal. The Recovery Plan says: "Classify
   counterparty for ₹Z on date D — would resolve 1 credit."

4. **Grouped action.** Five credits all need the same settlement report re-export for the same date
   window. They appear as ONE action with `resolves` = 5 keys and combined `recoverable_paise`.

## Success criteria

- **SC-001** Headline metrics (precision 1.000, recall, reconciled count, fee-GST) are
  byte-identical with and without the recovery step (additivity). Property test locks this.
- **SC-002** Recovery plan is deterministic: same inputs → identical plan ordering.
- **SC-003** The recovery step is read-only: it never mutates `ReconIndex`, attributions,
  reconciliations, or any input.
- **SC-004** Amounts are framed "up to ₹X if confirmed", never "₹X is owed."
- **SC-005** `resolve_delta` correctly identifies newly resolved credits and recovered paise.
- **SC-006** Actions capped at `max_actions` (default 20); truncation noted, not silent.
- **SC-007** No double-counting: a credit resolvable by two actions is counted once in
  `recoverable_if_actioned_paise`.

## Key entities
- **Hypothesis** — `{line_key, rail, weight, blocking_reason}`.
- **RecoveryAction** — `{action_type, params, resolves, recoverable_paise, cost, gain_per_cost}`.
- **RecoveryPlan** — `{actions, unresolved_count, unresolved_paise, recoverable_if_actioned_paise}`.

## Constitution check
- **Precision-first / abstain over guess**: the controller only *recommends*; it never asserts a
  credit is resolved or money is owed. ✓
- **Deterministic, stdlib-only**: pure functions over existing outputs; fixed cost weights. ✓
- **Additive**: no change to any attribution/reconciliation/GST metric; property test locks it. ✓
- **Honest metrics**: amounts are "up to … if confirmed"; coverage is never called precision. ✓
- **Read-only toward money**: no writes, no feedback into `ReconIndex`/reconciliation. ✓

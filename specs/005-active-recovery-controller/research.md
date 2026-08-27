# Research: Active Recovery Controller

Decisions resolving the design axes. Each is additive, deterministic, and grounded in the
existing `engine/exceptions.py` + `engine/evidence.py` control flow.

## D1 — Blocking-reason derivation (reuse existing signals, don't invent)

`blocking_reason` is derived deterministically from two sources that are already computed by the
pipeline: (a) `razorpay_signals(line, index)` + `narration_rail_signals(line)` from
`engine/evidence.py`, and (b) the credit's `ExceptionRecord.reason_code` from `engine/exceptions.py`.

The derivation logic:
- `razorpay_uncertain` exception + has brand/`settlement_ref`/`ifsc_ratn` but no UTR/amount/set-sum
  tie → `blocking_reason = "brand_no_tie"`.
- `razorpay_uncertain` exception + has `utr_suffix_weak` only → `blocking_reason = "weak_utr_suffix"`.
- `multiple_satisfying_subsets` exception → `blocking_reason = "ambiguous_setsum"`.
- `unattributed_ambiguous` exception (no Razorpay-leaning signal) → `blocking_reason = "unknown_sender"`.
- Ledger-related exception (`uncredited_settlement`, `partial_or_duplicate_settlement`,
  `unbalanced_residual`) → `blocking_reason = "ledger_exception"`.
- `rule_conflict` → `blocking_reason = "rule_conflict"` (mapped to `classify_counterparty` —
  needs human resolution).

No new signals are invented. `diagnose` reads from `razorpay_signals()` and
`narration_rail_signals()` to determine what evidence the credit *does* carry.

## D2 — Action taxonomy (fixed, cost-weighted)

Five action types with fixed cost weights. Costs are relative (lower = cheaper/easier for the
merchant). The mapping from `blocking_reason` to `action_type` is 1:1 (deterministic):

| blocking_reason     | action_type                | cost | rationale                              |
|---------------------|----------------------------|------|----------------------------------------|
| `brand_no_tie`      | `export_settlement_report` | 1.0  | Merchant re-exports from Razorpay dash |
| `weak_utr_suffix`   | `confirm_utr_with_bank`    | 2.0  | Requires bank interaction              |
| `ambiguous_setsum`  | `provide_settlement_ids`   | 1.5  | Merchant provides specific IDs         |
| `unknown_sender`    | `classify_counterparty`    | 0.5  | Cheapest: merchant knows the sender    |
| `ledger_exception`  | `reconcile_order_ledger`   | 1.0  | Merchant checks order/settlement IDs   |
| `rule_conflict`     | `classify_counterparty`    | 0.5  | Human must resolve rule conflict       |

## D3 — Grouping (same action, same params)

Credits that share an identical `(action_type, params)` key are grouped into ONE `RecoveryAction`.
`params` are built deterministically from the credit's date, amount, and identifiers. The
`resolves` tuple lists all grouped line_keys (sorted for determinism). `recoverable_paise` is
summed across the group's credits.

For `export_settlement_report`, `params` = `{"date_from": ..., "date_to": ...}` where the date
window is the credit's value_date ± `_SPLIT_DATE_WINDOW` (from `engine/attribute.py`). Credits
with overlapping date windows are merged into one action with the union window.

## D4 — Ranking (gain-per-cost, deterministic tie-break)

`gain_per_cost = recoverable_paise / cost`. Actions are sorted by:
1. `gain_per_cost` descending,
2. `recoverable_paise` descending (tie-break),
3. `action_type` ascending (final stable tie-break).

Cap at `max_actions` (default 20). If truncated, note it in a logged message; do not silently cap.

## D5 — No double-counting in `recoverable_if_actioned_paise`

A credit that appears in multiple actions' `resolves` sets is counted **once** in the plan-level
`recoverable_if_actioned_paise`. Implementation: set-union over all `resolves`, then sum the
unique credits' amounts.

## D6 — `resolve_delta` is a pure comparison, not a pipeline change

`resolve_delta(before_report, after_report)` compares two report dicts. It returns:
- `newly_resolved`: set of line_keys that were abstained/unattributed in `before` and are now
  attributed (non-UNKNOWN) in `after`.
- `newly_reconciled`: set of line_keys that were unreconciled in `before` and reconciled in `after`.
- `recovered_paise`: sum of amounts of newly resolved credits.

It is pure, deterministic, safe on identical inputs (empty delta), and never runs the pipeline.

## D7 — Additivity invariant

The recovery controller is a **post-pipeline pass**. It reads the outputs of attribution,
reconciliation, exceptions, and fee-GST, and produces a new `recovery_plan` section. It never
alters any input. The property test asserts byte-identical headline metrics with and without the
recovery step. This is the core guardrail.

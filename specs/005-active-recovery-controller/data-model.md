# Data Model: Active Recovery Controller

No persisted models. Pure functions over existing types; no fields added to existing models.

## New (in-memory) types — `engine/recovery.py`

### Hypothesis (frozen)
| field | type | meaning |
|---|---|---|
| `line_key` | `str` | key of the unresolved bank credit |
| `rail` | `str` | the rail this credit MIGHT be (`razorpay_settlement`, `other_gateway`, …) |
| `weight` | `float` | from the existing evidence scores (`_combine`); 0..1 |
| `blocking_reason` | `str` | why it isn't proven (e.g. `brand_no_tie`, `weak_utr_suffix`, `unknown_sender`) |

### RecoveryAction (frozen)
| field | type | meaning |
|---|---|---|
| `action_type` | `str` | from the action taxonomy (`export_settlement_report`, etc.) |
| `params` | `dict` | e.g. `{"date_from": "...", "date_to": "..."}` |
| `resolves` | `tuple[str, ...]` | line_keys this action could resolve (sorted, deterministic) |
| `recoverable_paise` | `int` | SUM of amounts of `resolves` credits (upper bound; "up to") |
| `cost` | `float` | fixed operational weight from the taxonomy |
| `gain_per_cost` | `float` | `recoverable_paise / cost` (the ranking key) |

### RecoveryPlan (frozen)
| field | type | meaning |
|---|---|---|
| `actions` | `tuple[RecoveryAction, ...]` | ranked, highest `gain_per_cost` first |
| `unresolved_count` | `int` | total number of unresolved credits |
| `unresolved_paise` | `int` | total amount of unresolved credits |
| `recoverable_if_actioned_paise` | `int` | sum over distinct resolvable credits (no double counting) |

## Unchanged — existing types reused as-is
- `ExceptionRecord` (`engine/models.py`) — reused, not replaced.
- `BankCreditLine` (`engine/models.py`) — read-only input.
- `RailAttribution` (`engine/models.py`) — read-only input (not modified by this feature).
- `ReconIndex` (`engine/evidence.py`) — read-only input.

## New report section
`RunReport.to_dict()` gains a top-level `recovery_plan` key containing the serialized
`RecoveryPlan`. This is additive — no existing keys are changed.

## Invariants (tested)
- Additivity: headline metrics byte-identical with/without the recovery step. Property test locks.
- Deterministic: same inputs → identical plan (ordering stable via multi-key sort).
- Read-only: no mutation of inputs (`ReconIndex`, attributions, reconciliations).
- Honest: `recoverable_paise` is an upper bound ("up to … if confirmed"); no double-counting
  across actions in `recoverable_if_actioned_paise`.

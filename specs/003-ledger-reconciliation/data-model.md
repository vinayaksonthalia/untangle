# Data Model: Order-Ledger Reconciliation

No new persisted models. The feature is a pure function over existing types and returns existing
`ExceptionRecord`s. This documents the entities it reads and the exceptions it emits.

## Inputs (existing types, unchanged)

### OrderLedgerEntry  (engine/models.py)
| field | type | meaning |
|---|---|---|
| `order_id` | `str \| None` | the merchant's order identifier (join key); `None` → un-linkable |
| `amount_paise` | `int` | order amount, integer paise |
| `status` | `str` | merchant's belief (see research.md Decision 2) |
| `created_at` | `datetime \| None` | booking time |

### ReconRow  (engine/models.py) — the settlement side
Relevant fields: `type`, `entity_id`, `order_id`, `settlement_id`, `credit_paise`, `debit_paise`,
`dispute_id`, `net_paise`. A settlement's `order_id`s are the join targets; `dispute_id`/refund
`type` rows signal refunds/chargebacks.

### Reconciliation outputs (from `reconcile()`)
- `list[ReconciliationResult]` — the proven slice; each covers `covered_entity_ids` → their `ReconRow`s → their `order_id`s.
- `SettlementIndex` — `rows_by_sid`, `net_by_sid`, and existing exception sets.

## Derived indices (built inside engine/ledger.py, in-memory)
- `settled_order_ids: set[str]` — order_ids covered by a **reconciled** settlement.
- `order_id → settlement contribution` — for amount agreement checks (± tolerance).
- `ledger_by_order_id: dict[str, list[OrderLedgerEntry]]` — to detect duplicates (list length > 1).
- `refunded_order_ids: set[str]` — order_ids whose settlement carries a refund/dispute row.

## Output: ExceptionRecord  (existing model, reused)
| field | value for a ledger exception |
|---|---|
| `line_key` | the ledger order_id (namespaced, e.g. `order:<order_id>`), or the covering settlement id where the anchor is a settlement |
| `reason_code` | one of the four new codes below |
| `detail` | human-readable, amounts formatted, naming the order/settlement |
| `suggested_action` | concrete next step for a finance owner |
| `evidence` | `list[EvidenceItem]` — the ledger row(s) and settlement/recon reference(s) compared |

### Reason codes (state → exception)
| reason_code | when |
|---|---|
| `uncredited_order` | order believed-paid in ledger, no id-match in any reconciled settlement (money possibly owed) |
| `ledger_mismatch` | reconciled settlement's order is missing from the ledger, or present with a contradicting status / out-of-tolerance amount |
| `duplicate_order_booking` | the same order_id appears >1× in the ledger for a single settled payment |
| `refund_not_reflected` | settlement carries a refund/dispute for an order the ledger still marks fully paid |

## Invariants (enforced by tests)
- Emitting these exceptions **does not** alter attributions, reconciliations, or the headline metrics (additivity).
- Deterministic: same three files → identical exception set (ordering stable, e.g. by `(reason_code, line_key)`).
- Empty/missing/id-less ledger → zero ledger exceptions, no error.
- No exception asserts a clean order↔settlement link without an id match AND amount agreement within tolerance.

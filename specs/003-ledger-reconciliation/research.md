# Research: Order-Ledger Reconciliation

Decisions that resolve the ambiguous axes in the spec. Each is a deterministic, precision-first
choice consistent with the constitution.

## Decision 1 — Join key: `order_id`
- **Decision**: Link a ledger order to a settlement via `order_id`, which exists on both
  `OrderLedgerEntry.order_id` and `ReconRow.order_id`. A reconciled settlement's covered entities
  map back to their `ReconRow`s (hence their `order_id`s).
- **Rationale**: It is the only shared, stable identifier between the merchant's book and the recon
  report. Amount alone is coincidental (the whole engine already treats amount as corroboration,
  not proof); date alone is weaker still.
- **Alternatives considered**: amount+date fuzzy match (rejected — reintroduces the exact
  coincidental-match risk the proof-gate removed); a new synthetic key (rejected — nothing to hash on).

## Decision 2 — Recognised ledger status vocabulary
- **Decision**: Treat a small, documented set as "believed paid": `paid`, `captured`, `settled`,
  `success`, `completed` (case-insensitive). Treat `refunded`, `reversed`, `chargeback`, `disputed`
  as "refund/dispute noted". Everything else (including empty) is **unknown status** — never assumed
  paid or failed.
- **Rationale**: Precision-first — an unrecognised status must not be silently interpreted as paid
  (which would create a false "uncredited money" alarm) nor as failed (which would hide a real one).
- **Alternatives considered**: assume any non-empty status = paid (rejected — false positives);
  require an exact single status (rejected — real ledgers vary).

## Decision 3 — Amount tolerance
- **Decision**: Reuse the engine's existing `_DRIFT_TOLERANCE_PAISE` (±₹1) for any amount comparison
  between a ledger order and its settlement contribution. A difference beyond tolerance is surfaced
  (as a mismatch), never absorbed.
- **Rationale**: Consistency with reconciliation; a labelled rounding drift is expected, a larger gap
  is a real discrepancy.

## Decision 4 — When to ABSTAIN (never assert a wrong link)
- **Decision**: The feature only *asserts* an order↔settlement relationship when the `order_id`
  matches AND the amounts agree within tolerance. If the id matches but the amount does not (or vice
  versa), it does not claim a clean link — it surfaces the item as an ambiguous mismatch for review.
  A paid order with no id-match in any settlement → `uncredited_order`. It never force-matches by
  amount/date.
- **Rationale**: Mirrors the proof-gate: resemblance is not proof. A false "this order settled" is as
  harmful as a false "this credit is Razorpay's".

## Decision 5 — Additivity (no verdict/metric change)
- **Decision**: `engine/ledger.py` is a pure function over already-computed outputs
  (`reconciliations`, `recon_rows`, `SettlementIndex`) plus the ledger; it returns only new
  `ExceptionRecord`s. It is wired into `build_report` to *append* to the exception list — it never
  feeds back into attribution or reconciliation.
- **Rationale**: Guarantees SC-003 (precision/recall/reconciled/fee-GST unchanged), enforced by a
  property test that runs the pipeline with and without the ledger step and diffs the headline totals.

## Decision 6 — Reason codes & surfacing
- **Decision**: Four codes — `uncredited_order`, `ledger_mismatch`, `duplicate_order_booking`,
  `refund_not_reflected` — each an `ExceptionRecord` with reason, human detail, evidence trace, and a
  suggested action. Rendered by the existing dashboard exception queue (just add labels/colours) and
  the new `contracts/ledger-exceptions.md` documents them.
- **Rationale**: Reuse the proven `ExceptionRecord`/`build_exceptions` honesty pattern rather than a
  parallel structure.

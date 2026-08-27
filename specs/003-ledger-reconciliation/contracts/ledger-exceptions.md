# Contract: Ledger Exception Classes

The public "interface" of this feature is the set of exception classes it adds to the report's
exception queue. Each is an `ExceptionRecord` (existing schema) with the fields below. These codes
are stable identifiers consumers (dashboard, CSV/JSON export, a CA) may rely on.

## `uncredited_order`
- **Trigger**: a ledger order in a believed-paid status whose `order_id` matches no *reconciled*
  Razorpay settlement.
- **Meaning**: the merchant thinks this money arrived; the proven settlement slice does not show it.
  Potentially lost revenue, a stuck settlement, or a non-Razorpay rail.
- **Evidence**: the ledger row (order_id, amount, status, date); the fact that no reconciled
  settlement covers this order_id.
- **Suggested action**: "Verify against the gateway settlement report — this paid order has no
  matching Razorpay settlement."
- **Never**: force-match by amount/date. If an id match exists but the amount disagrees, this is a
  `ledger_mismatch`, not `uncredited_order`.

## `ledger_mismatch`
- **Trigger**: a reconciled settlement's `order_id` is (a) absent from the ledger, or (b) present but
  in a status contradicting a completed settlement, or (c) present with an amount outside ±₹1 tolerance.
- **Meaning**: money provably settled, but the merchant's books disagree — a booking error.
- **Evidence**: the settlement id + order_id; the ledger row (or its absence); observed vs expected status/amount.
- **Suggested action**: "Correct the order's status/amount in your ledger to match the settled payment."

## `duplicate_order_booking`
- **Trigger**: the same `order_id` appears more than once in the ledger while mapping to a single
  settled payment.
- **Meaning**: the same order was booked twice — revenue could be double-counted.
- **Evidence**: the ≥2 ledger rows sharing the order_id; the single settlement covering it.
- **Suggested action**: "De-duplicate this order in your ledger; only one booking is backed by a settlement."

## `refund_not_reflected`
- **Trigger**: a settlement carries a refund/dispute (`type` refund, or a `dispute_id`) for an
  `order_id` the ledger still marks fully paid.
- **Meaning**: a refund/chargeback happened but the books still count the full amount as revenue.
- **Evidence**: the settlement refund/dispute row + amount; the ledger row still marked paid.
- **Suggested action**: "Record the refund/chargeback against this order so revenue isn't overstated."

## Guarantees (contract-level)
- Every record carries a non-empty `detail`, `suggested_action`, and `evidence` list.
- These records are **additive**: their presence never changes any attribution/reconciliation verdict
  or the headline precision/recall/reconciled/fee-GST numbers.
- Deterministic: identical inputs produce an identical, stably-ordered set of these records.
- Read-only: no record implies or triggers a money movement or a write to the ledger.

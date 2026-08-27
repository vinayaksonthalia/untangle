
## Order-ledger discrepancy classes (Feature 003)

Aggregated (one summary record per class) cross-checks of the merchant's order ledger against the
PROVEN Razorpay slice. Additive — never change an attribution/reconciliation verdict or metric.

- **`ledger_mismatch`** — settled orders (money confirmed in the bank) that are missing from the
  ledger, or whose single unambiguous booking contradicts the settlement on status or amount (±₹1).
- **`duplicate_order_booking`** — a settled (Razorpay-attributed) order_id booked more than once.
- **`refund_not_reflected`** — a reconciled refund/dispute on a singly-booked order the ledger still marks paid.

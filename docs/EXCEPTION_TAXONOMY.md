# Exception Taxonomy & Recovery Mapping

Exceptions in untangle represent credits or orders that cannot be automatically resolved with
mathematical certainty. Rather than force-matching or guessing, untangle routes them to an auditable
exception queue, which feeds into the [Active Recovery Controller](ACTIVE_RECOVERY.md).

---

## 1. Bank-Credit Exceptions & Recovery Actions

These exceptions are keyed by real bank-statement credit `line_key`s and directly inform the next-best
recovery actions:

| Reason Code | Source / Phase | Root Condition | Mapped Recovery Action |
|---|---|---|---|
| `unattributed_ambiguous` | Attribution | Insufficient signal to attribute credit to any rail. | `classify_counterparty` |
| `rule_conflict` | Attribution | Contradictory human-approved rules matched the line. | `classify_counterparty` |
| `multiple_satisfying_subsets` | Reconstruct splits | Bounded set-sum found multiple distinct subsets summing to net. | `provide_settlement_ids` |
| `razorpay_coverage_not_found` | Reconciliation | Attributed Razorpay, but settlement rows are missing. | `export_settlement_report` |
| `unbalanced_residual` | Reconciliation | Settlement rows found, but net residual exceeds tolerance. | `export_settlement_report` |
| `reconstructed_split_leg` | Reconstruct splits | Reconstructed leg awaiting entity-level reconciliation. | `export_settlement_report` |
| `partial_or_duplicate_settlement` | Reconciliation | Settlement row is split across multiple credits or duplicated. | `export_settlement_report` |

For detailed ranking mechanics and action parameters, see [Active Recovery Controller](ACTIVE_RECOVERY.md).

---

## 2. Order-Ledger Discrepancy Classes (Feature 003)

Aggregated (one summary record per class) cross-checks of the merchant's order ledger against the
PROVEN Razorpay slice. Additive — never change an attribution/reconciliation verdict or metric.
These use synthetic `"ledger:*"` keys and report order-level discrepancies:

- **`ledger_mismatch`** — settled orders (money confirmed in the bank) that are missing from the
  ledger, or whose single unambiguous booking contradicts the settlement on status or amount (±₹1).
- **`duplicate_order_booking`** — a settled (Razorpay-attributed) order_id booked more than once.
- **`refund_not_reflected`** — a reconciled refund/dispute on a singly-booked order the ledger still marks paid.

---

## 3. Reconciliation Variance Root-Cause Taxonomy (Feature 006)

For credits that attribute to Razorpay but exhibit reconciliation failures (`unbalanced_residual`,
`partial_or_duplicate_settlement`, `reconstructed_split_leg`, `razorpay_coverage_not_found`), the
[Agentic Exception Investigator](AGENTIC_INVESTIGATION.md) classifies the underlying root cause:

| Root Cause Class | Description & Resolution | Proposed Corrective Voucher |
|---|---|---|
| `mdr_fee_drift` | MDR fee-slab recompute or GST tax-inside/outside convention difference accounts for variance. | `Payment Gateway Charges` vs `Razorpay Clearing A/c` |
| `cross_cycle_refund_lag` | In-cycle refund whose settlement timing spans across cycles accounts for variance. | `Cross-Cycle Refund Suspense A/c` |
| `on_hold_release` | On-hold transaction amount withheld or released matches delta. | `On-Hold Settlement Reserve A/c` |
| `dispute_deduction` | Dispute / chargeback deduction matches variance. | `Disputed Receivables A/c` |
| `partial_capture` | Partial capture on payment accounts for delta. | `Uncaptured Order Variance A/c` |
| `bank_charge_or_rounding` | Variance $\le \pm ₹1$ rounding drift or standard bank fees. | `Bank Charges & Rounding` |
| `rolling_reserve` | Explicit rolling reserve record in data matches variance (*gated on real schema data*). | `Rolling Reserve Asset A/c` |
| `unexplained` | No category closes variance within tolerance $\to$ strictly abstains. | None (no entry drafted) |

For complete reasoning trace semantics and journal proposals, see [Agentic Investigation](AGENTIC_INVESTIGATION.md).



# Active Recovery Controller (Feature 005)

When untangle abstains to preserve ledger integrity, it does not leave the merchant with a dead-end
list of unexplained credits. The **Active Recovery Controller** turns abstentions and reconciliation
exceptions into a ranked, actionable recovery plan.

---

## 1. The Recovery Loop

Reconciliation in production is not a single one-off batch; it is an iterative loop:

```
                  ┌──────────────────────┐
                  │ 1. Run Reconciliation│
                  │    (precision-first) │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ 2. Diagnose & Form   │
                  │    Hypotheses        │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ 3. Rank Actions by   │
                  │    Gain-per-Cost     │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ 4. Operator Actions  │
                  │    (export, confirm) │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ 5. Rerun & Diff via  │
                  │    resolve_delta()   │
                  └──────────────────────┘
```

1. **Precision-First Run**: Credits are attributed and reconciled against available data. Ambiguous or uncorroborated credits abstain.
2. **Diagnosis**: Every unresolved credit is diagnosed to determine *why* it was blocked.
3. **Action Ranking**: Concrete recovery actions are generated, grouped, and ranked by expected recoverable impact per unit cost.
4. **Action Execution**: The finance team executes high-gain actions (e.g., pulling a missing 5-day settlement window or asking a bank for a full UTR).
5. **Rerun Diff**: A rerun with updated data calls `resolve_delta(before, after)` to measure newly resolved credits and recovered paise.

---

## 2. Blocking Reasons & Action Taxonomy

| Derived Blocking Reason | Root Cause | Recommended Action | Cost |
|---|---|---|:---:|
| `brand_no_tie` | Narration names Razorpay, but no UTR or matching settlement row exists in the loaded recon report. | `export_settlement_report`<br>*(Params: `date_from`, `date_to` ±5d)* | 1.0 |
| `recon_failure` | Attributed to Razorpay, but settlement reconciliation failed (`razorpay_coverage_not_found`, `unbalanced_residual`, `reconstructed_split_leg`, `partial_or_duplicate_settlement`). | `export_settlement_report`<br>*(Params: `date_from`, `date_to` ±5d)* | 1.0 |
| `weak_utr_suffix` | A 4-character UTR suffix matches, but date or amount drifts outside safe thresholds. | `confirm_utr_with_bank`<br>*(Params: `date`, `amount_paise`)* | 2.0 |
| `ambiguous_setsum` | Multiple distinct combinations of settlement nets sum to the credit amount. | `provide_settlement_ids`<br>*(Params: `date`, `amount_paise`)* | 1.5 |
| `unknown_sender`<br>`rule_conflict` | No brand signals or ties; or human-approved rules contradict each other. | `classify_counterparty`<br>*(Params: `date`, `amount_paise`, optional `bank_ref`)* | 0.5 |

*Note: Order-ledger discrepancy classes (`ledger_mismatch`, `duplicate_order_booking`, `refund_not_reflected`) are synthetic order-level exceptions and are intentionally out-of-scope for per-bank-credit recovery actions.*

---

## 3. Information-Gain Ranking

Recovery actions are prioritized by expected information gain per unit operator effort:

$$\text{gain\_per\_cost} = \frac{\text{recoverable\_paise}}{\text{cost}}$$

- **Action Grouping**: Identical actions (same action type and identical parameters) are grouped into a single recommendation. Their recoverable amounts are summed.
- **Deterministic Sort**: Ranked by `(-gain_per_cost, -recoverable_paise, action_type, tuple(sorted_resolves))`.
- **Set Union (No Double Counting)**: `recoverable_if_actioned_paise` computes the distinct set union of credits resolved by the actions in the plan. A credit is never counted twice.
- **Honest Capping**: Capped at `max_actions` (default 20). If truncated, `plan.note` explicitly records that the plan is capped at the top actions.

---

## 4. Recovery Trail Diff (`resolve_delta`)

`resolve_delta(before_report: dict, after_report: dict) -> dict` is a pure function that compares two serialized report outputs:

```python
delta = resolve_delta(before_report, after_report)
# Returns:
# {
#   "newly_resolved": ["k_credit1", "k_credit2"],
#   "newly_reconciled": ["k_credit1", "k_credit2"],
#   "recovered_paise": 4500000
# }
```

- Safe on identical reports (returns empty lists and 0 paise).
- Does not mutate input dictionaries.
- Decoupled from execution: never triggers or reruns the pipeline itself.

---

## 5. Non-Negotiable Invariants

1. **Additive**: Running with recovery does not alter attributions, reconciliations, fee-GST, exceptions, or any headline metric.
2. **Precision-First & Honest**: Actions are *recommendations*, never assertions. Descriptions always read `"up to ₹X recoverable across N credit(s) if confirmed"`, never `"owed"`.
3. **Deterministic & Stdlib-Only**: Pure Python, no new runtime dependencies, and zero LLM calls in decision logic.

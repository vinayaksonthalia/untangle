# Agentic Exception-Investigation Loop (Feature 006)

When a Razorpay bank credit fails to reconcile cleanly against the settlement report, untangle does not
guess or force a balancing debit. Instead, the **Agentic Exception-Investigation Loop** autonomously diagnoses
the variance from underlying settlement and transaction data, outputs a deterministic audit trace, tests competing
hypotheses (preserving the negative space of rejected candidates), and drafts a balanced corrective double-entry
voucher.

---

## 1. Overview & Architecture

While the **Active Recovery Controller** ([`docs/ACTIVE_RECOVERY.md`](ACTIVE_RECOVERY.md)) resolves *missing data*
by recommending external evidence acquisition (such as fetching settlement reports or confirming UTRs), the
**Agentic Exception Investigator** addresses **reconciliation discrepancies where data is present but the money
does not tie out**:

```
 ┌────────────────────────┐
 │ Bank Credit Line (₹)   │
 └───────────┬────────────┘
             │ (Variance != 0)
 ┌───────────▼────────────────────────────────────────────┐
 │  Deterministic Root-Cause Classification Engine        │
 │  (Pure Python, stdlib-only, ordered taxonomy)          │
 └───────────┬────────────────────────────────────────────┘
             │
 ┌───────────▼────────────────────────────────────────────┐
 │  Investigation Result:                                 │
 │  • Root Cause Diagnosis (or 'unexplained' abstention)  │
 │  • Deterministic Confidence Metric (0.0 .. 1.0)        │
 │  • Human-Readable Reasoning Trace                      │
 │  • Evaluated Candidates (showing rejected space)       │
 │  • Balanced Corrective Journal Proposal                │
 └────────────────────────────────────────────────────────┘
```

---

## 2. Root-Cause Taxonomy & Classification Rules

Every reconciliation variance is evaluated through an ordered sequence of deterministic tests. If no category
closes the variance within the $\pm ₹1$ tolerance, the engine strictly **abstains** (`root_cause = "unexplained"`),
never hallucinating a cause.

| Root Cause | Diagnostic Condition | Corrective Journal Action |
|---|---|---|
| **`mdr_fee_drift`** | Recomputation of gateway MDR fee structure (including GST tax-inside vs tax-outside conventions) closes the variance. | Adjusts `Payment Gateway Charges` vs `Razorpay Clearing A/c`. |
| **`cross_cycle_refund_lag`** | A customer refund or chargeback processed in this settlement period whose settlement timing lagged across cycle boundaries accounts for the variance. | Posts to `Cross-Cycle Refund Suspense A/c`. |
| **`on_hold_release`** | An on-hold reserve held from (or released into) the settlement cycle matches the variance amount. | Adjusts `On-Hold Settlement Reserve A/c`. |
| **`dispute_deduction`** | A chargeback or disputed transaction deduction in the settlement accounts for the delta. | Posts to `Disputed Receivables A/c`. |
| **`partial_capture`** | Authorized payment amount differs from captured amount, with the delta matching the bank discrepancy. | Posts to `Uncaptured Order Variance A/c`. |
| **`bank_charge_or_rounding`** | Variance is within standard $\pm ₹1$ rounding drift or small fixed bank transaction charges. | Posts to `Bank Charges & Rounding`. |
| **`rolling_reserve`** | An explicit rolling reserve deduction or release record present in the settlement schema matches the delta (*strictly gated on real data; never inferred*). | Adjusts `Rolling Reserve Asset A/c`. |
| **`unexplained`** | None of the above categories closes the variance within tolerance. | **Abstains**: no journal entry drafted (`corrective_entry = None`). |

---

## 3. Worked Example: MDR Fee Tax Drift

### Input Bank Credit & Settlement Data
- **Bank Credit**: ₹9,728.00 (972,800 paise)
- **Settlement Expected Net**: ₹9,764.00 (976,400 paise)
- **Variance**: −₹36.00 (−3,600 paise)
- **Settlement Tax on Fee**: ₹36.00 (3,600 paise)

### Output Reasoning Trace
```
Step 1: Computed variance: Bank credit (₹9,728.00) vs Expected settlement net (₹9,764.00) -> Delta: -₹36.00 (-3600 paise).
Step 2: Evaluated 'mdr_fee_drift' -> MATCH: Fee tax-inside/outside convention difference matches variance: ₹36.00.
Step 3: Drafted balanced corrective double-entry journal proposal (Proposed adjustment for mdr_fee_drift | Bank credit k_9f8dafbd274120b1 | Variance -₹36.00 | PROPOSAL ONLY - NOT POSTED).
```

### Proposed Balanced Corrective Entry
```
Ref: ADJ-setl_001
Date: 2024-04-10
Narration: Proposed adjustment for mdr_fee_drift | Bank credit k_9f8dafbd274120b1 | Variance -₹36.00 | PROPOSAL ONLY - NOT POSTED
Balanced: True

Ledger Accounts:
  - Debit:  Payment Gateway Charges   ₹ 36.00
  - Credit: Razorpay Clearing A/c     ₹ 36.00
```

---

## 4. Evaluated Candidates (The Negative Space)

To ensure full auditability, the engine preserves not only the winning root cause, but the exact rationale for
why alternative explanations were rejected:

```json
[
  {
    "root_cause": "mdr_fee_drift",
    "matched": true,
    "delta_paise": -3600,
    "unexplained_residual_paise": 0,
    "reason": "Fee tax-inside/outside convention difference matches variance: ₹36.00"
  },
  {
    "root_cause": "cross_cycle_refund_lag",
    "matched": false,
    "delta_paise": 0,
    "unexplained_residual_paise": 3600,
    "reason": "No cross-cycle refund row matches the variance amount."
  },
  {
    "root_cause": "on_hold_release",
    "matched": false,
    "delta_paise": 0,
    "unexplained_residual_paise": 3600,
    "reason": "No matching on-hold transactions in settlement."
  }
]
```

---

## 5. Non-Negotiable Invariants

1. **Deterministic Decision Core**: No LLM in the decision loop. All classifications and calculations are stdlib-only pure functions.
2. **Deterministic Confidence**: Confidence is calculated as a pure mathematical function of residual error ($1.0$ for exact 0-error matches, scaled for minor rounding tolerance), not a heuristic LLM score.
3. **Additive & Read-Only**: Attaching investigations never modifies headline numbers, attributions, reconciliations, or fee GST. Corrective vouchers are proposals, never auto-posted.
4. **Abstain Over Guess**: If no hypothesis matches the data, the system outputs `root_cause = "unexplained"` and omits journal drafts.

---

## 6. Investigation Companion Benchmark

`python -m generator.generate --seed 42 --scale 1.0 --out data` leaves the established
attribution benchmark unchanged and also writes `data/investigation/`. This companion dataset
contains explicitly labelled bank/report discrepancies for every deterministic root-cause class,
plus an unsupported control that must abstain. Run it through the normal CLI:

```bash
python -m engine.cli run \
  --bank data/investigation/bank_statement.csv \
  --recon data/investigation/recon_report.json \
  --ledger data/investigation/order_ledger.csv \
  --out out/investigation --no-ai --seed 42
```

Each companion label records `intended_root_cause`, `report_expected_net_paise`,
`bank_evidence_amount_paise`, and `expected_variance_paise`. `eval.metrics.score()` exposes the
separate additive `investigation_resolution` metric; these cases never alter attribution
precision/recall or the core reconciliation and fee-GST figures.

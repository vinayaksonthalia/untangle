# Quickstart: Active Recovery Controller Demo

This quickstart demonstrates the closed-loop recovery workflow introduced in Feature 005.

---

## The 60-Second Demo Scenario

### 1. The Problem
A merchant uploads a bank statement where **3 Razorpay settlement credits** have corrupted narrations (mangled UTRs caused by bank truncations). Additionally, the merchant's initial Razorpay settlement export was cut off and is missing those settlement rows.

### 2. The Precision-First Initial Run
`untangle` processes the batch. Following its constitution:
- Brand words in narration are corroboration, never proof.
- Because no exact UTR tie or settlement net exists in the initial report, `untangle` **refuses to guess** and abstains on all 3 credits.
- Razorpay precision remains **1.000**.

In the CLI output and dashboard, the **Active Recovery Plan** appears immediately:

```
Active Recovery Plan: 1 recommended action(s) · up to ₹7,13,058.27 recoverable if confirmed
    1. Export Razorpay settlement report (2026-01-03 to 2026-01-08) — up to ₹7,13,058.27 recoverable across 3 credits if confirmed
```

### 3. Taking the Action
The operator logs into the Razorpay merchant dashboard and exports the settlement report covering the suggested date range (`2026-01-03` to `2026-01-08`).

### 4. Closed-Loop Rerun Diff
The merchant reruns `untangle` with the fuller settlement report.

Calling `resolve_delta(before_report, after_report)` in Python or reviewing the rerun output displays:

```json
{
  "newly_resolved": [
    "k_1780498800xp8vma",
    "k_1780498801xp8vmb",
    "k_1780498802xp8vmc"
  ],
  "newly_reconciled": [
    "k_1780498800xp8vma",
    "k_1780498801xp8vmb",
    "k_1780498802xp8vmc"
  ],
  "recovered_paise": 71305827
}
```

### 5. Why This Wins
- **A naive matcher** would either force-match on the word "RAZORPAY" (risking false positives on decoys or fee reversals) or discard them.
- **A passive matcher** leaves them as unexplained, manual review items with no guidance.
- **untangle's Active Recovery Controller** stays 100% precise (zero guesses) while giving the operator the exact, ranked action that recovers the money.

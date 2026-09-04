# Razorpay public sample reports — provenance

These files are **Razorpay's own published sample reports**, downloaded verbatim
and unmodified from Razorpay's public documentation CDN. They are vendored here so
untangle's correctness can be checked against data **untangle did not author** — the
settlement groupings, the per-transaction fees, and the credit/debit legs were all
decided by Razorpay's billing engine, not by our generator.

That is the whole point: when untangle's model reproduces the money identity in this
file to the paise, it is reproducing a property of *Razorpay's* ledger, not of our
own synthetic benchmark.

| File | Downloaded | SHA-256 |
|---|---|---|
| `sample-settlements-recon-report.xlsx` | 2026-09-04 | `d2a238c7876bbe7b57274edade200a91803cc6964a3e9b3052f312b35caabdbd` |

**Source URL** (verified 200 OK, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`):
`https://razorpay.com/docs/build/browser/assets/images/sample-settlements-recon-report.xlsx`

Referenced from Razorpay's reports documentation:
`https://razorpay.com/docs/pos/dashboard/reports/`

Column schema confirmed against Razorpay's Settlement Recon API doc
(`https://razorpay.com/docs/api/settlements/fetch-recon/`): `entity_id`, `type`
(payment/refund/…), `amount`, `fee`, `tax`, `debit`, `credit`, `settlement_id`,
`settled_at`, `settlement_utr`. In this report the fee column is labelled
`fee (exclusive tax)` and `tax` (18% GST on the fee) is itemised separately; untangle
folds the two into its `fee_paise` (tax-inside-fee) convention, and keeps `tax_paise`
for the GST-on-fee schedule.

## What is checked against it

`tests/evidence/test_razorpay_public_samples.py` (no network, no API key, no extra
dependency — parsed with the Python standard library) loads this file through
untangle's own `ReconRow` model and `SettlementIndex`, and asserts:

1. **Per-row money identity** — for every payment `credit == amount − fee − tax` with
   `debit == 0`; for every refund `debit == amount` with `credit == 0`.
2. **Per-settlement cross-column consistency** — independently reads each expected net from the
   raw workbook payment amount/fee/tax columns minus refund amount (not from mapped
   `ReconRow` fields or credit/debit), then
   asserts `SettlementIndex.net_by_sid[sid]` matches to the paise. This cross-column
   check includes the settlement whose members include a refund (money **out**, a
   debit — the sign trap that fools naive "amount ≈ total" matchers).
   Negative controls corrupt payment credit and refund debit by one paise and verify
   that the comparison detects both errors. This is not verification against a
   separately published settlement-level total or a bank statement.
3. **Money conservation** — every amount is an exact integer number of paise; no
   fractional paise is introduced anywhere in the load.

## Honest scope

This is Razorpay's small *illustrative* sample (unit-rupee transactions), not a real
merchant's production volume. The test proves untangle **ingests and conserves
Razorpay's own published money legs exactly**, including refund sign handling — it is
not a claim about reconciliation accuracy on a real bank statement, which untangle
measures separately and reports honestly per upload.

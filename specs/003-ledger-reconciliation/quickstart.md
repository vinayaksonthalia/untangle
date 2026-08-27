# Quickstart: Validate Order-Ledger Reconciliation

Prove the feature works end-to-end and stays within the constitution.

## Prerequisites
- The seeded dataset exists: `python -m generator.generate --seed 42 --scale 1.0 --out data`
- The pipeline runs: `python -m engine.cli run --bank data/bank_statement.csv --recon data/recon_report.json --ledger data/order_ledger.csv --out out/`

## Scenario A — the third file now changes the output (SC-002)
1. Run the pipeline as above (with the ledger).
2. Inspect `out/report.json` exceptions: at least one ledger-class exception
   (`uncredited_order` / `ledger_mismatch` / `duplicate_order_booking` / `refund_not_reflected`)
   is present.
3. **Expected**: providing the ledger produces ledger exceptions that are absent when the ledger is
   empty — the third file earns its place.

## Scenario B — additivity: no verdict/metric change (SC-003)
1. `python -m eval.sealed` (or score `out/report.json`) — record razorpay precision, recall,
   reconciled count, recoverable fee-GST.
2. Confirm these equal the pre-feature numbers (precision 1.000, recall 0.911, 91 reconciled,
   ₹43,200.99). The property test `tests/property/test_ledger_additive.py` asserts this automatically.
3. **Expected**: identical headline numbers — the feature is additive.

## Scenario C — each reason code fires on a crafted batch (SC-001)
Run `pytest tests/unit/test_ledger.py`. It builds small in-memory batches and asserts:
- a paid order with no reconciled settlement → `uncredited_order`;
- a reconciled settlement whose order is missing/contradicted in the ledger → `ledger_mismatch`;
- a doubly-booked order_id → `duplicate_order_booking`;
- a settlement refund the ledger doesn't reflect → `refund_not_reflected`;
- an id match with a disagreeing amount → surfaced as a mismatch, **never** a silent clean link.

## Scenario D — safe on a missing/empty ledger (SC-005)
1. Run the pipeline with an empty ledger (header only).
2. **Expected**: zero ledger exceptions, no error, unchanged attribution/reconciliation output.

## Scenario E — dashboard surface (FR-010)
1. Open `out/report.json` in the dashboard (`python -m ui.dashboard --run out/report.json --out ui/dashboard.html`).
2. **Expected**: the ledger exceptions appear in the exception queue, grouped by reason, each with a
   reason label, detail, evidence, and suggested action.

## Done when
All five scenarios pass and `pytest` (unit + property) is green, with the headline metrics unchanged.

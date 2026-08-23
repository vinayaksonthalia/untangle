# `untangle` — synthetic-data generator

Seeded, reproducible generator of a **multi-rail bank-credit attribution**
benchmark for the Track-4 project. It emits three linked artifacts plus an
answer key. **It contains no matcher, no attribution logic, and no solver** —
only data and labels. Keep this directory out of the matcher session's context
(isolation protocol, EXCEPTION_TAXONOMY.md §"Isolation protocol").

## What it produces (into `data/`)

| File | What it is |
|---|---|
| `recon_report.json` | Razorpay settlement recon rows, in the **verified field shape** (`fixtures/recon_sdk_node_2026-08-21.md`). JSON array of row objects. |
| `order_ledger.csv` | Merchant order ledger (order_id, amount, GST slab 5/12/18%, status, timestamps) — deliberately messy, simulating a Shopify/Tally/WooCommerce export. |
| `bank_statement.csv` | **The centerpiece.** Commingled, multi-rail bank statement. Only *some* credit lines are Razorpay settlements. Amounts in **rupees** (2 dp) — a real friction; ground truth is in paise. |
| `ground_truth.json` | Answer key: for every bank line, its true rail; and for razorpay lines, the settlement_id(s)/UTR(s) and the exact `(type, entity_id)` recon rows it covers. |
| `manifest.json` | Seed, scale, per-rail counts, per-hard-case counts, row counts, and a SHA-256 of every output file — so a reviewer can reproduce and verify. |

## How to run

```bash
# default scale -> ~12.4k recon rows, ~257 bank lines
python3 -m generator.generate --seed 42 --scale 1.0 --out data

# small/fast for tests
python3 -m generator.generate --seed 7 --scale 0.05 --out /tmp/mini

# knobs
#   --seed        master seed (all randomness derives from it)
#   --scale       linear volume multiplier (1.0 ≈ 11k payments)
#   --base-epoch  UTC seconds base for ALL timestamps (no wall clock is ever read)
#   --days        statement window length
```

Reproducibility: same `--seed/--scale/--base-epoch/--days` ⇒ **byte-identical**
outputs (verified by re-running and comparing the manifest SHA-256s). No
`time.time()`, no unseeded `random` anywhere in the data logic.

The generator is **fail-closed**: it runs `selfcheck.py` (conservation
invariants, below) *before* writing any file. If ground truth ever disagreed
with the data it labels, generation aborts instead of emitting a bad benchmark.

## Money & schema facts honored (verified against `fixtures/`)

- Money is **paise** (integer subunits).
- `payment_id` is **NULL** on `payment` rows (the `pay_*` id is in `entity_id`);
  populated on refund/transfer rows. Join on `(type, entity_id)`, never `payment_id`.
- `tax` is 18% GST **on the fee, included within `fee`** (transfer: `debit = amount + fee`).
  `credit(payment) = amount − fee`. We never add tax on top.
- `method` ∈ {`card`,`netbanking`,`wallet`,`upi`,`emi`}; `card_*` are NULL for non-card.
- `notes` is a **string or null** (never an object).
- `transfer` rows: `order_id` NULL, `method`/`card_*` NULL.
- `adjustment` rows: `order_id`/`payment_id`/`settlement_utr` NULL, and `credit_type` is **omitted** (V10).
- UPI carries **zero fee** (P2M ~zero-MDR) — so a fee-variance detector correctly
  reports "no detectable variance" rather than manufacturing findings (PROJECT_SPEC 4b).

## Noise / commingling taxonomy (rates are config, in `config.py::NoiseRates`)

Every hard case, its default injection rate, and why it exists. Rates are the
`NoiseRates` fields, not magic numbers; changing them there changes the table.

### Bank-side (statement) — taxonomy B1–B4

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Commingled non-Razorpay credits (multi-rail) | rail block ratios | ~54% of lines non-rzp | B2: only some credits are Razorpay; the account also receives other-PG payouts, direct UPI, COD remittances, and unrelated credits. This *is* the attribution problem. |
| Mangled/truncated UTR in narration | `mangled_utr_rate` | 0.15 | B1: banks truncate/space/upper-case/drop chars of the UTR; ID match on narration alone fails. |
| One settlement → two bank credits (split) | `split_settlement_rate` | 0.08 | V6/B: Razorpay splits a payout across value-dates when the amount exceeds live balance. Two lines, different days, same settlement_id. |
| Two settlements → one same-day credit (merge) | `merge_settlement_rate` | 0.06 | B3: two settlements clubbed into one bank credit; the line covers rows from two settlement_ids. |
| Paise rounding drift | `rounding_drift_rate` | 0.10 | M4: displayed bank credit differs from the true net by ±1–7 paise; exact-equality match fails. Drift is labeled so the answer key stays exact. |
| Bank charge / reversal debit lines | `bank_charge_per_week` | 2.0 / week | B4: NEFT/RTGS charges + GST interleaved as debit lines that belong to no settlement. |
| Carry-forward (net ≤ 0 settlement rolls into next) | derived | as needed | A refund/dispute-heavy settlement never lands as a credit; Razorpay carries it into the next positive settlement. Labeled `carry_forward`. |

### Recon-side (settlement) — taxonomy V1–V8

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Cross-cycle refunds | `cross_cycle_refund_rate` | 0.35 | V5: refund settles in a later batch than its original payment; per-batch balancing fails. |
| On-hold rows (never hit bank this cycle) | `on_hold_rate` | 0.02 | V7: `settled=false`; money in the report that isn't in the bank. Never covered by any line. |
| Dispute / chargeback debit rows | `dispute_rate` | 0.015 | V8: `dispute_id` populated; debit lands in a later settlement. |
| Route transfer rows | `transfer_rate` | 0.03 | V2: `trf_*` rows, `order_id` NULL, resolve via parent payment. |
| Adjustment rows (no join key) | `adjustment_per_batch` | 0.35 / batch | V1: `adj_*` rows with no order/payment/UTR key; explainable only from free text + amount. |
| Unexplained fee variance | `fee_variance_rate` | 0.03 | PROJECT_SPEC §4: a fraction of non-UPI rows deviate from their cluster's modal effective rate; feeds the fee-variance module. Never injected on UPI. |

### Merchant-ledger corruption — taxonomy M1/M2 (in `noise.py`)

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Missing `order_id` | `order_id_missing_rate` | 0.04 | M1: blank export cell. |
| Mangled `order_id` | `order_id_mangled_rate` | 0.03 | M1: truncated / lower-cased / whitespace / `order_` prefix stripped / adjacent-char typo. |
| Duplicate order row | `order_id_duplicate_rate` | 0.02 | M2: the same order exported twice. |

The **recon report stays clean**; only the merchant's own ledger export is
corrupted. That asymmetry is realistic: the vendor's report is tidy, the
merchant's spreadsheet is not.

## Conservation self-check (`selfcheck.py`, runs before writing)

- **I1** — every razorpay line's `true_amount_paise` equals the sum of
  `(credit − debit)` over its covered recon rows, to the paise.
- **I2** — displayed bank credit = `true_amount_paise + rounding_drift_paise`
  (drift is the *only* permitted discrepancy).
- **I3** — every settled, non-on-hold recon row in a settlement is covered by
  **exactly one** razorpay line (nothing lost, nothing double-counted).
- **I4** — no on-hold row is ever covered by a bank line (V7).
- **I5** — bijection between bank `line_id`s and ground-truth labels.

## Module map

```
generator/
  config.py      Config + NoiseRates (all rates live here)
  rng.py         seeded named RNG streams (no wall clock, no global random)
  ids.py         Razorpay-shaped ids + UTR
  build.py       CLEAN orders + recon rows + settlement batches
  narration.py   per-rail bank narration templates + UTR mangling (B1/B2)
  noise.py       merchant-ledger corruption (M1/M2)
  bank.py        multi-rail bank statement + ground truth (the centerpiece)
  selfcheck.py   conservation invariants (fail-closed)
  generate.py    CLI entry point; writes files + manifest
  DECISIONS.md   1–2 lines per non-obvious choice
```

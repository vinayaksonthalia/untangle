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
# default scale -> ~12.4k recon rows, ~294 bank lines
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
- **RuPay debit** is likewise **zero-MDR** (RBI zero-rating) — its modal rate is 0.

## Noise / commingling taxonomy (rates are config, in `config.py::NoiseRates`)

Every hard case, its default injection **rate**, and why it exists. Every
injection-rate knob is a named `NoiseRates` field; changing it there changes the
table. A small, explicitly-enumerated set of **intentional constants** is NOT
promoted to config because they are arithmetic facts or fixed catalogs, not
"how often" knobs — see "Intentional constants" at the end of this section.

### Bank-side (statement) — taxonomy B1–B4

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Commingled non-Razorpay credits (multi-rail) | rail block ratios | ~54% of lines non-rzp | B2: only some credits are Razorpay; the account also receives other-PG payouts, direct UPI, COD remittances, and unrelated credits. This *is* the attribution problem. |
| Mangled/truncated UTR in narration | `mangled_utr_rate` | 0.30 | B1: banks truncate/space/upper-case/drop chars of the UTR; ID match on narration alone fails. |
| …of which the UTR epoch prefix is DESTROYED | `mangled_prefix_destroy_share` | 0.55 | SERIOUS-2: prefix dropped/replaced so the UTR can't be recovered from its 10-digit epoch prefix (spec edge case "mangled beyond recovery from the prefix"). |
| One settlement → two bank credits (split) | `split_settlement_rate` | 0.08 | V6/B: Razorpay splits a payout across value-dates when the amount exceeds live balance. Two lines, different days, **each with its OWN bank UTR**, shared settlement_id. |
| Two settlements → one same-day credit (merge) | `merge_settlement_rate` | 0.06 | B3: two settlements clubbed into one bank credit; the line covers rows from two settlement_ids. |
| Paise rounding drift | `rounding_drift_rate` | 0.10 | M4: displayed bank credit differs from the true net by ±1–7 paise; exact-equality match fails. Drift is labeled so the answer key stays exact. |
| Bank charge / reversal debit lines | `bank_charge_per_week` | 2.0 / week | B4: NEFT/RTGS charges + GST interleaved as debit lines that belong to no settlement. |
| Carry-forward (net ≤ 0 settlement rolls into next) | `carry_forward_rate` | 0.04 of batches | A refund/dispute-heavy settlement never lands as a credit; Razorpay carries it into the next positive settlement. Batches are deliberately starved of payments and seeded with refund debits so this fires. Labeled `carry_forward`. |

### Adversarial hardening — defeat single-key baselines (FR-016 / SC-003)

The benchmark MUST NOT be solvable by any one trivial key (brand keyword, unique
amount, or clean UTR). These knobs guarantee that; `difficulty_probe.py` proves
each naive baseline fails on the class below while staying high on the easy
majority.

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Brand-less razorpay settlements | `brandless_rate` | 0.22 | Narration carries only a sponsor-bank IFSC + UTR, no `RAZORPAY`/`RZPX` token — a brand grep MISSES these (spec edge case). |
| Razorpay-looking decoys (non-rzp) | `decoy_brandish_rate` | 0.18 × rzp | A RazorpayX payout / personal reimbursement / rzp UPI-handle collect / Razorpay-Capital loan carries a brand token but is NOT the merchant's settlement — a brand grep FALSE-positives (SC-008). |
| Amount collisions | `amount_collision_rate` | 0.20 | A non-rzp line shares the EXACT displayed credit of a razorpay line, so amount is not a key; amount-only join false-positives. |
| UTR echoed nowhere | `utr_absent_rate` | 0.20 (of non-mangled) | `ref_no` is a bank-assigned txn id, not the settlement UTR, and the UTR is absent from the narration — clean-UTR join finds nothing. |
| value_date jittered off settlement | `value_date_jitter_rate` | 0.60 | Bank value_date is ±1–2 days off `settled_at`, so `value_date` no longer equals the UTR's epoch prefix and a value_date+amount recovery of a mangled UTR fails (SERIOUS-2). |

### Recon-side (settlement) — taxonomy V1–V8

| Case | Config rate | Default | Rationale |
|---|---|---|---|
| Refunds (of settled payments) | `refund_rate` | 0.08 | Fraction of settled payments that spawn a refund debit row (was a hardcoded 0.08; now config — SERIOUS-4). |
| …of which partial | `partial_refund_rate` | 0.40 | Fraction of refunds that are partial (a quarter/half/three-quarter refund) rather than full. |
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

### Intentional constants (NOT injection rates — deliberately inline)

These are arithmetic facts or fixed catalogs, not "how often" knobs, so they live
inline (each annotated at its definition) rather than on `NoiseRates`:

- **`GST_ON_FEE_RATE = 0.18`** and the **`MODAL_RATE_*` MDR table** (`config.py`)
  — a fixed pricing catalog. RuPay-debit and UPI MDR are `0.0000` (zero-rated).
- **`transfer_base_fee_rate` / `refund_rate` / `partial_refund_rate`** — these
  *were* hardcoded and are now promoted to `NoiseRates` (SERIOUS-4).
- **Rounding-drift magnitude set** `[-7,-5,-3,-2,-1,1,2,3,5,7]` paise (`bank.py`)
  — the *rate* is `rounding_drift_rate`; the magnitude spread is a fixed ±paise range.
- **Sample bank-charge amounts** `[1180, 2360, 590, 2950]` paise incl. GST
  (`bank.py`) — a fixed catalog of realistic NEFT/RTGS/AMC charges; the *rate*
  is `bank_charge_per_week`.
- **Fee-variance direction** is now a 50/50 RNG draw (`build.py`), not amount
  parity — so variance is not ~90% one-directional (MINOR fix).

## Adversarial-difficulty probe (`difficulty_probe.py`)

Proves the benchmark is adversarial (FR-016 / SC-003). Runs three naive
single-key baselines against the blind ground truth and prints precision/recall
per hard-case class:

```bash
python3 -m generator.difficulty_probe --data data
```

Each baseline stays ~100% on the easy majority but **collapses** on the class it
is blind to: brand grep → 0% recall on `brand_less` and ~100% false-positive on
`decoy_brandish`; clean-UTR join → 0% recall on `mangled_utr` / `prefix_destroyed`
/ `utr_absent` / `split_settlement`; amount-only join → 0% recall on split/merge/
carry and a high false-positive rate on `amount_collision` decoys. No single key
achieves high precision **and** recall alone.

## Conservation self-check (`selfcheck.py`, runs before writing)

- **I1** — every razorpay line's `true_amount_paise` equals the sum of
  `(credit − debit)` over its covered recon rows, to the paise.
- **I2** — displayed bank credit = `true_amount_paise + rounding_drift_paise`
  (drift is the *only* permitted discrepancy).
- **I3** — every settled, non-on-hold recon row in a settlement is covered by
  **exactly one** razorpay line (nothing lost, nothing double-counted).
- **I4** — no on-hold row is ever covered by a bank line (V7).
- **I5** — bijection between bank `line_id`s and ground-truth labels.

Adversarial-hardening invariants (the benchmark must contain the cases it claims,
so no metric rests on an absent hard class):

- **I6** — every `brand_less` razorpay line's narration carries NO brand token.
- **I7** — every `prefix_destroyed` line hides the UTR's 10-digit epoch prefix.
- **I8** — every `decoy_brandish` line is a non-razorpay rail carrying a brand token.
- **I9** — every `amount_collision` razorpay line shares its exact displayed
  credit with at least one non-razorpay bank line (amount is not a key).
- **I10** — at least one `carry_forward` bank line actually exists.

## Module map

```
generator/
  config.py      Config + NoiseRates (all rates live here)
  rng.py         seeded named RNG streams (no wall clock, no global random)
  ids.py         Razorpay-shaped ids + UTR
  build.py       CLEAN orders + recon rows + settlement batches
  narration.py   per-rail bank narration templates + UTR mangling (B1/B2)
  noise.py       merchant-ledger corruption (M1/M2)
  bank.py            multi-rail bank statement + ground truth (the centerpiece)
  selfcheck.py       conservation + adversarial invariants (fail-closed)
  generate.py        CLI entry point; writes files + manifest
  difficulty_probe.py  naive single-key baselines vs truth (adversarial proof)
  DECISIONS.md       1–2 lines per non-obvious choice
```

# DECISIONS — `untangle` generator

One or two sentences per non-obvious choice: why it exists, and why the simpler
thing is wrong.

- **Ground truth is keyed on `(type, entity_id)`, never `payment_id`.** Verified
  fact V3: `payment_id` is NULL on payment rows. Keying labels on `payment_id`
  would silently drop every payment row — the exact bug the matcher must avoid,
  so the answer key must not commit it either.

- **`tax` is emitted *inside* `fee`, not added on top.** Fixture transfer row
  proves `debit = amount + fee` (not `+ tax`). Modeling tax as an extra deduction
  would make every conservation sum wrong by the GST amount.

- **UPI rows get zero fee, and fee-variance is never injected on UPI.**
  PROJECT_SPEC 4b: P2M UPI is ~zero-MDR. Injecting UPI variance would train the
  matcher to "find" fee anomalies that don't exist in reality — a manufactured
  finding, which the spec explicitly forbids.

- **The recon report is clean; only the merchant ledger is corrupted.** Real
  asymmetry: Razorpay's report is machine-generated and tidy; the merchant's
  Shopify/Tally export is messy. Corrupting the recon report instead would test
  a problem merchants don't actually have.

- **Bank amounts are rupees (2 dp); ground truth is paise.** A real bank
  statement is in rupees, and the unit mismatch is a genuine matcher friction.
  Emitting paise in the bank file would hide that friction and make the benchmark
  too easy.

- **Rounding drift is a *labeled* discrepancy; `true_amount_paise` stays exact.**
  The bank line shows `true + drift`, but the answer key records the exact net and
  the drift separately. If drift leaked into the label, the conservation
  self-check would be meaningless and the eval couldn't distinguish a correct
  match from a lucky one.

- **Net ≤ 0 settlements roll forward into the next positive settlement
  (`carry_forward`), rather than being dropped.** A refund-heavy settlement never
  lands as a bank credit in reality; Razorpay carries it. Dropping such batches
  would orphan their recon rows (no bank line covers them) and violate the
  "nothing vanishes" invariant; emitting a negative "credit" would be unrealistic.

- **Split legs partition the recon rows (not the amount).** Each leg's displayed
  amount is the exact net of *its* row subset, so conservation holds per leg.
  Splitting by amount alone would leave the covered-row sets ambiguous and make
  the answer key impossible to verify exactly.

- **A `line_id` column is added to the bank statement.** Real statements have no
  stable line id, but a labeled benchmark needs a join key between statement and
  answer key. We surface it explicitly rather than relying on row order (which
  CSV round-trips and re-sorts can break). The matcher must not treat `line_id`
  as attribution signal — it is only a join handle.

- **Randomness is split into named, seed-derived streams (`rng.py`).** Each
  logical stream (amounts, methods, timestamps, …) is seeded from
  `sha256(seed:name)`. Using one global RNG would mean adding any new draw
  re-shuffles every downstream value, breaking reproducibility across code edits.

- **All timestamps derive from `--base-epoch`.** No `time.time()` in data logic.
  Wall-clock time would make outputs non-reproducible and the manifest hashes
  meaningless.

- **`credit_type` is omitted on adjustment rows (not set to null).** Fixture
  evidence V10: the razorpay-node fixture omits the field on the adjustment row
  while docs include it. Emitting it would erase a real vendor-source
  disagreement the parser must tolerate.

- **`selfcheck` runs before any file is written (fail-closed).** A generator that
  can silently emit inconsistent ground truth is worse than useless — it would
  produce a benchmark whose "answers" are wrong. Aborting on any invariant
  violation guarantees the shipped data is internally consistent.

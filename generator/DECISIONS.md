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

## Adversarial hardening (FR-016 / SC-003) — defeat single-key baselines

- **No single trivial key may solve attribution.** A prior audit found the
  benchmark over-determined by three redundant keys: globally-unique amounts,
  100% brand-keyword separability, and a clean UTR echoed verbatim into `ref_no`
  for ~89% of lines. Each is now deliberately broken; `difficulty_probe.py`
  proves each naive baseline fails on the class it is blind to while staying high
  on the easy majority.

- **Brand-less razorpay settlements + Razorpay-looking decoys.** A share of real
  settlements carry only a sponsor-bank IFSC + UTR (no brand token), and some
  non-razorpay lines carry a brand token but are not settlements (RazorpayX
  payout, personal reimbursement, rzp UPI handle, Razorpay-Capital loan). So a
  brand grep gets both false negatives and false positives — a keyword filter is
  provably insufficient, and abstaining on a decoy beats a false "this is rzp".

- **Amount collisions.** Some non-razorpay lines share the exact displayed credit
  of a razorpay line, so an amount join is not a key. Emitting the decoy at the
  same paise (not "close") makes the collision unambiguous in the answer key.

- **UTR: mangled-with-prefix-destroyed, or echoed nowhere; split legs get their
  own bank UTR.** A clean-UTR join now finds nothing on a real share of lines.
  Crucially, `value_date` is jittered ±1–2 days off `settled_at`, so `value_date`
  no longer equals the UTR's epoch prefix — closing the value_date+amount
  recovery of a mangled UTR that the audit found (the old value_date == UTR-epoch
  identity made "mangling" cosmetic).

- **carry_forward is now constructed, not hoped for.** The old roll-forward code
  existed but never fired (every batch had positive-net payments). We now reserve
  a config-rated fraction of batches, starve them of payments, and seed them with
  refund debits so their net is strictly ≤ 0 — guaranteeing the case occurs, and
  invariant I10 fails-closed if it ever doesn't.

- **Fee-variance direction is an RNG draw, not amount parity.** The old
  `amount % 2` test made variance ~90% one-directional (an artifact a detector
  could learn). Direction is now a 50/50 seeded draw.

- **Promoted refund/partial-refund/transfer-fee rates to `NoiseRates`; remaining
  inline values are annotated structural constants.** The claim "every rate is a
  named config field" was false (refund 0.08, partial 0.4, transfer base-fee
  0.0025 were hardcoded). The genuinely structural constants (GST-on-fee, the MDR
  catalog, the drift-magnitude set, the sample bank-charge amounts) stay inline,
  each annotated, and the README claim now scopes to *injection-rate* knobs.

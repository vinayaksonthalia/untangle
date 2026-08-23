# untangle

**Attribution-first reconciliation for commingled merchant bank accounts.**

Razorpay's settlement recon report already matches ~90% of a merchant's settled
transactions by ID. `untangle` does not rebuild that. It solves the step that comes
*before* reconciliation and that existing tools assume away: **when a real merchant's
bank account receives money from many rails at once — Razorpay settlements, a second
gateway, direct UPI, COD remittances, loan disbursals, personal transfers — which
credits are even Razorpay's?**

Only once each bank credit is correctly attributed to its rail can the Razorpay slice
be reconciled and the recoverable fee-GST (input tax credit) be surfaced.

## Approach

- **Deterministic first.** Rail attribution runs through tiered deterministic rules
  (UTR-format fingerprints, per-rail narration patterns, amount-graph correlation
  against the settlement report). Matching and arithmetic are never done by an LLM.
- **LLM only on the residue.** Ambiguous free-text bank narrations that rules can't
  resolve go to a language model — nothing else. A no-AI ablation reports exactly how
  much the model adds.
- **Calibrated abstention.** A false "this is Razorpay's" corrupts everything
  downstream, so the engine can say **UNKNOWN** with a measured cost — attribution
  *precision* is the headline metric, not raw match rate.
- **Honest by construction.** Every schema claim cites a committed vendor fixture
  (`fixtures/`, verified by `scripts/verify_schema_claims.py`). Synthetic data is
  grounded in publicly documented bank and payment-rail formats, not invented.

## Status (active development)

- [x] Multi-rail synthetic data generator (seeded, reproducible, self-checking; proven
      adversarial — `generator/difficulty_probe.py`)
- [x] Attribution engine (deterministic tiers A/B/C + calibrated abstention; LLM at the edge)
- [x] Reconciliation of the Razorpay slice + recoverable fee-GST (paise-exact)
- [x] Honest exception list + `why` trace
- [x] Evaluation harness (per-rail **and per-hard-case** precision/recall, decoy FP, ablation)
- [ ] Demo UI

### Measured (seed 42, deterministic `--no-ai`, scored vs blind ground truth)

- Attribution precision **1.000** on every rail; **0 decoy false-positives** (naive brand-grep: 100%).
- Out-of-sample (4 unseen seeds): precision 1.000 and 0 decoy-FP hold; recall 0.86–0.94.
- Reconciliation: **91/91 covered sets exact** vs ground truth, to the paise.
- Recoverable fee-GST surfaced from Razorpay's own tax-on-fee, per-transaction traceable.
- Every miss is an **abstention**, never a misattribution — surfaced as a named exception.

See [docs/mvp-eval-results.md](docs/mvp-eval-results.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
and [docs/EXPLAINED.md](docs/EXPLAINED.md).

## Reproduce the data

The dataset is not committed (it is regenerated from a seed). One command:

```bash
python3 -m generator.generate --seed 42 --scale 1.0 --out data
```

Byte-identical across runs (SHA-256s recorded in `data/manifest.json`). The generator
is fail-closed: conservation invariants in `generator/selfcheck.py` must pass before
any file is written. Noise taxonomy and injection rates: `generator/README.md`.

## Layout

```
generator/   synthetic multi-rail data + ground-truth labels (no matcher logic)
data/        generated artifacts (gitignored) + manifest.json
fixtures/    real Razorpay recon samples + provenance (schema source of truth)
scripts/     verify_schema_claims.py — every schema claim, checked against fixtures
EXCEPTION_TAXONOMY.md   the exception/rail classes, with evidence
INCIDENTS.md            real failures during the build, and what changed
```

## License

MIT (see LICENSE).

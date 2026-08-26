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

## Headline: Attribution & Calibrated Abstention (PR-004)

`untangle` leads with attribution precision and honest abstention — never a single bare match rate:

- **Attribution Precision: 1.000 (100%)** on every rail; **0 decoy false-positives** across 181 non-Razorpay lines (naive brand-matching hits 100% false-positives).
- **Calibrated Abstention (ECE = 0.0876 ≤ 0.10)**: when evidence is ambiguous, the engine explicitly abstains as `UNKNOWN` with named reasons and evidence traces.
- **Zero forced set-sum picks**: enumerates all satisfying subsets; where >1 subset satisfies a credit amount, it abstains (forced picks = 0 up to candidate set $N=200$).
- **Human-proposed rules (G5 / FR-009)**: rules proposed upon human resolution remain inert until approved, apply only on confident matches, and never lower the precision bar.

### Precision-at-Coverage & Abstention Curve (294-line benchmark)

| Confidence Cutoff | Coverage % | Abstention Rate % | Attributed Credits | Abstained Credits | Razorpay Precision | Decoy FP Rate |
|---|---|---|---|---|---|---|
| **$\tau \ge 0.50$** | **96.3%** | **3.7%** | 283 | 11 | **1.000** | 0.000 (0/181) |
| **$\tau \ge 0.60$** | **94.9%** | **5.1%** | 279 | 15 | **1.000** | 0.000 (0/181) |
| **$\tau \ge 0.70$** | **83.7%** | **16.3%** | 246 | 48 | **1.000** | 0.000 (0/181) |
| **$\tau \ge 0.80$** | **82.3%** | **17.7%** | 242 | 52 | **1.000** | 0.000 (0/181) |
| **$\tau \ge 0.90$** | **80.6%** | **19.4%** | 237 | 57 | **1.000** | 0.000 (0/181) |
| **$\tau \ge 0.95$** | **80.6%** | **19.4%** | 237 | 57 | **1.000** | 0.000 (0/181) |

---

### Reconciliation & Recoverable ITC (Proven Slice Only)

Reconciliation runs **only** on credits proven to be Razorpay's:

- **Paise-exact reconciliation**: 91/91 covered sets balanced to the paise (±₹1 labelled rounding drift); zero forced balancing entries.
- **Traceable Fee-GST (ITC)**: ₹43,201 in recoverable input tax credit surfaced directly from Razorpay's tax-on-fee, 100% itemized and traceable.
- **FR-016 exception handling**: duplicate, split, partial, and unbalanced settlements surface cleanly as exceptions with actionable next steps.

## Status (Completed Phases 1–5)

- [x] Multi-rail synthetic data generator (seeded, reproducible, self-checking; proven adversarial)
- [x] Attribution engine (deterministic tiers A/B/C + correlation-aware Noisy-OR calibration ECE ≤ 0.10)
- [x] Set-sum enumerate-all-and-abstain (zero forced picks across $N \in [10, 200]$)
- [x] Paise-exact reconciliation of proven Razorpay slice + recoverable fee-GST (ITC)
- [x] Exception queue with evidence traces & human-proposed versioned rules (G5/FR-009/G6)
- [x] Evaluation harness & generator-blind sealed holdout runner (`eval/sealed.py`)
- [x] Privacy-by-construction web app and dashboard UI (PR-001..PR-004)

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

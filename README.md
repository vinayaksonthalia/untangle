<div align="center">

# untangle

**Which credits in your bank account are even Razorpay's?**

*Attribution-first reconciliation — every bank credit tied to its source rail with evidence,
or abstained. Never a guessed match.*

[![Try the live demo](https://img.shields.io/badge/▶_TRY_THE_LIVE_DEMO-2b5edb?style=for-the-badge)](#quickstart)
[![Run it locally](https://img.shields.io/badge/RUN_IT_LOCALLY-14140f?style=for-the-badge)](#quickstart)

![CI](https://github.com/vinayaksonthalia/untangle/actions/workflows/ci.yml/badge.svg)
![tests](https://img.shields.io/badge/tests-129_passing-1b7a4d)
![precision](https://img.shields.io/badge/Razorpay_precision-1.000-1b7a4d)
![abstains](https://img.shields.io/badge/abstains-never_guesses-b4720a)
![python](https://img.shields.io/badge/python-3.12-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-web_+_API-009688)
![license](https://img.shields.io/badge/license-MIT-8957e5)

</div>

---

> A real merchant's current account receives money from many rails at once — Razorpay settlements,
> a second gateway, direct UPI, COD remittances, loan disbursals, personal transfers — all as
> undifferentiated bank credits. **Before you can reconcile anything, you have to know which credit
> is even Razorpay's.** Nobody solves that step. They assume it away.

untangle solves it — and it is **precision-first**: a credit is only called Razorpay's when there is a
genuine tie back to the settlement report (an exact UTR, a corroborated UTR suffix, a provably-unique
set-sum of settlement nets, or an amount that uniquely matches one settlement net). A brand word in the
narration, the Razorpay IFSC, or a look-alike amount are **corroboration, never proof**. When the proof
isn't there, untangle **abstains** — it routes the credit to a review queue with a reason, rather than
booking a wrong "this is Razorpay's" that would corrupt the ledger.

Only once each credit is attributed can the Razorpay slice be reconciled to the paise and the recoverable
GST on gateway fees (input tax credit) be surfaced.

## Why this is hard — and why a matcher fails

The naive approach matches on brand words and round amounts. But a competitor payout, a refund, or a
personal transfer can carry the word "razorpay" in the narration *and* happen to equal a settlement total.
On a labelled 294-line adversarial benchmark, naive single-key matchers are either **blind** (miss the
Razorpay credits whose UTR was mangled) or **fooled** (label look-alike decoys as Razorpay):

| Baseline (single key) | Razorpay precision | Razorpay recall |
|---|---|---|
| amount-only | 0.84 | 0.80 |
| brand-word-only | 0.83 | 0.86 |
| clean-UTR-only | 1.000 | 0.52 |
| **untangle** (tiered evidence + abstention) | **1.000** | **0.91** |

*(Reproduce: `python -m generator.difficulty_probe` — same blind ground truth for every row.)*

## What you get

- **Attribution with evidence** — every bank credit labelled Razorpay / other-gateway / direct-UPI / COD /
  transfer / **review**, each with the exact evidence trace behind the verdict.
- **Paise-exact reconciliation** of the proven Razorpay slice — 91/91 covered sets balanced to ±₹0
  (±₹1 labelled rounding drift), zero forced balancing entries.
- **Recoverable fee-GST (ITC)** — a per-transaction, traceable input-tax-credit schedule from Razorpay's
  own tax figures.
- **Split-settlement reconstruction** — when one bank credit is the sum of several settlement legs,
  untangle recovers the legs by a *provably-unique* subset-sum (and abstains on ambiguity).
- **Order-ledger reconciliation** — cross-checks the proven slice against your order ledger
  (uncredited / missing / duplicate / refund-not-reflected).
- **Proof Packets** — a per-credit evidence receipt (JSON/CSV) for every verdict; the whole run is auditable.
- **An adversarial challenger** — before accepting any attribution, untangle actively tries to *disprove*
  it and reports a proof margin. It knows when *not* to act.

## Measured — precision first, never a bare match rate

On a sealed, generator-blind adversarial holdout (n ≈ 294, 14 narration-corruption modes):

- **Razorpay attribution precision: 1.000** — zero false "this is Razorpay's".
- **0 decoy false-positives** across 181 look-alike non-Razorpay credits.
- **Recall 0.91** on true Razorpay credits (0.84 on the blind sealed set) — the rest abstain, never guessed.
- **±₹0 residual** on every reconciled credit; unresolved credits are surfaced, not forced.

Honest scope: these are measured on a labelled adversarial benchmark, **not** a claim about every
real-world statement. On your own unlabelled upload, untangle shows attributed-vs-abstained counts and a
real coverage curve, and never asserts a precision it cannot measure.

## Quickstart

untangle is a real product, not a demo — upload your **own** three files and get a real reconciliation.
The bundled sample just lets you see it work instantly.

```bash
git clone https://github.com/vinayaksonthalia/untangle && cd untangle
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"

# generate the seeded sample dataset (byte-identical across runs)
python3 -m generator.generate --seed 42 --scale 1.0 --out data

# run the web app  →  http://localhost:8080
uvicorn webapp.app:app --port 8080
```

- `/` landing · `/app` upload your three files · `/try-sample` instant sample run · `/api/docs` the JSON API.
- **Bring your own data:** a bank statement CSV (`value_date · narration · credit · debit`), the Razorpay
  settlement report JSON (`entity_id · type · amount · fee · tax · settlement_utr`), and your order ledger
  CSV (`order_id · amount_paise · status`). Processed in a per-request temp directory and deleted the
  moment the report renders — nothing is persisted.

Or run the pipeline headless:

```bash
python -m engine.cli run --bank data/bank_statement.csv --recon data/recon_report.json \
  --ledger data/order_ledger.csv --out out/
```

Deploy your own (Docker / Render one-click): see [`docs/DEPLOY.md`](docs/DEPLOY.md).

## How it works

```
                     ┌──────────────┐
 bank statement ───▶ │  ATTRIBUTE   │  tie each credit to a rail with evidence
 recon report ─────▶ │  (proof-gate │  → Razorpay only on a genuine tie
 order ledger ─────▶ │  + abstain)  │  → no tie? abstain to the review queue
                     └──────┬───────┘
                            ▼
         ┌───────────────── proven Razorpay slice ─────────────────┐
         ▼                        ▼                        ▼
   RECONCILE to paise      RECOVER fee-GST (ITC)     LEDGER cross-check
         │                        │                        │
         └──────────── PROOF PACKETS (per-credit receipts) ┘
```

Every step is deterministic and read-only toward money. The intelligence is in the judgment: tiered
evidence (A: exact UTR · B: scored weak evidence · C: bounded set-sum), calibrated abstention, and an
adversarial challenger that tries to disprove each verdict before accepting it.

## Repository layout

```
engine/       attribution, proof-gate, reconciliation, split reconstruction, ledger, proof packets
generator/    seeded multi-rail synthetic data + blind ground-truth labels (no matcher logic)
eval/         evaluation harness, sealed holdout runner, calibration
webapp/       FastAPI app — landing, upload, live reconcile, JSON API
ui/           the dashboard renderer
specs/        spec-driven development trail (constitution → spec → plan → tasks per feature)
docs/         ARCHITECTURE, DEPLOY, EXCEPTION_TAXONOMY, EXPLAINED, and more
INCIDENTS.md  real failures during the build, and what changed
```

## Reproduce the data

The dataset is not committed — it is regenerated from a seed, byte-identical across runs (SHA-256s in
`data/manifest.json`). The generator is fail-closed: conservation invariants in `generator/selfcheck.py`
must pass before any file is written.

```bash
python3 -m generator.generate --seed 42 --scale 1.0 --out data
```

## License

MIT — see [LICENSE](LICENSE).

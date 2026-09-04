<div align="center">

# untangle

**Close your Razorpay settlement books — with proof, not guesses.**

*An agent that closes one finance-ops loop across a 50+ record batch: it reconciles your bank credits
to Razorpay settlements to the paise, reports its match rate and the exceptions it refuses to guess,
proves every verdict, and hands you a balanced journal entry ready to post to Tally.*

[![Run on the web](https://img.shields.io/badge/▶_RUN_ON_THE_WEB-2b5edb?style=for-the-badge)](#quickstart)
[![Run it locally](https://img.shields.io/badge/RUN_IT_LOCALLY-14140f?style=for-the-badge)](#quickstart)

![CI](https://github.com/vinayaksonthalia/untangle/actions/workflows/ci.yml/badge.svg)
![tests](https://img.shields.io/badge/tests-passing-1b7a4d)
![precision](https://img.shields.io/badge/Razorpay_precision-1.000-1b7a4d)
![abstains](https://img.shields.io/badge/abstains-never_guesses-b4720a)
![python](https://img.shields.io/badge/python-3.12-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-web_+_API-009688)
![license](https://img.shields.io/badge/license-Apache--2.0-8957e5)

</div>

---

### Why it matters

- **The 5% that eats most of the work.** Most settlement lines auto-match on day one; it's the tail —
  mangled UTRs, split settlements, cross-cycle refunds — that eats the bulk of a finance team's
  reconciliation time (a widely-reported industry pattern, not a figure we measured here). untangle is
  built for that tail.
- **It refuses to guess — because a wrong match is expensive.** In India an unexplained or mis-matched
  credit can attract ~78% tax (Section 115BBE). So untangle only calls a credit "Razorpay's" when the
  settlement report *proves* it, and abstains otherwise. Precision is a financial safeguard, not a nicety.
- **It surfaces the GST on your gateway fees.** For each reconciled settlement, untangle extracts the
  GST Razorpay charged on its fee (from Razorpay's own tax figures) into a per-transaction schedule — the
  input-tax-credit line your accountant can then assess for eligibility. untangle reports the figures; it
  does not make the ITC-eligibility judgment for you.
- **It hands you postable books.** The output isn't a report to eyeball — it's a balanced double-entry
  journal (Tally XML + JSON), with an independently-verifiable audit trail behind every number.

### The hard part underneath: which credit is even Razorpay's?

> A real merchant's current account receives money from many rails at once — Razorpay settlements,
> a second gateway, direct UPI, COD remittances, loan disbursals, personal transfers — all as
> undifferentiated bank credits. **Before you can reconcile anything, you have to know which credit
> is even Razorpay's.** Most reconciliation tools start *after* that line — they take a credit already
> labelled Razorpay and decompose it into payments, fees, and GST. untangle solves the step before:
> proving, against look-alike decoys from every other rail, which bank credits are Razorpay's at all.

untangle solves it — and it is **precision-first**: a credit is only called Razorpay's when there is a
genuine tie back to the settlement report (an exact UTR, a corroborated UTR suffix, a provably-unique
set-sum of settlement nets, or an amount that uniquely matches one settlement net). A brand word in the
narration, the Razorpay IFSC, or a look-alike amount are **corroboration, never proof**. When the proof
isn't there, untangle **abstains** — it routes the credit to a review queue with a reason, rather than
booking a wrong "this is Razorpay's" that would corrupt the ledger.

Only once each credit is attributed can the Razorpay slice be reconciled to the paise and the recoverable
GST on gateway fees (input tax credit) be surfaced.

## Safety & guarantees

untangle is safer by design: **read-only toward money.** Full detail in [SAFETY.md](SAFETY.md).

- ✅ Read-only toward money — no code path can move, transfer, or debit funds
- ✅ No posting — corrective journal entries are balanced **proposals**, marked "not posted"
- ✅ Abstains rather than guesses — refuses to assert a match it cannot prove
- ✅ Every verdict is evidence-backed; deterministic, exact integer paise
- ✅ Independently verifiable close certificate (content SHA-256 + proof packets; ECDSA P-256 when signed, else hash-bound)
- ✅ Privacy by construction — processed in memory, no application database
- ☐ SOC 2 / ISO 27001 / statutory sign-off — **not claimed**
- ☐ Native per-bank export adapters (HDFC/ICICI/…) — planned, not shipped
- ☐ Benchmarks are synthetic unless a real dataset is explicitly named

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

- **Attribution with evidence, in four honest provenance classes** — **Razorpay-proven** (a report-backed
  tie), **non-Razorpay** (a distinctive signal points to another rail — a claim about *not*-Razorpay, never
  inferred from mere absence of evidence), **ambiguous**, and **unattributed** — each with the exact evidence
  trace. Only Razorpay is *proven*; the alternate rail is recorded as finer evidence, never over-claimed.
- **Paise-exact reconciliation** of the proven Razorpay slice — 91/91 covered sets balanced to ±₹0
  (±₹1 labelled rounding drift), zero forced balancing entries.
- **Recoverable fee-GST (ITC)** — a per-transaction, traceable input-tax-credit schedule from Razorpay's
  own tax figures.
- **Split-settlement reconstruction** — when one bank credit is the sum of several settlement legs,
  untangle recovers the legs by a *provably-unique* subset-sum (and abstains on ambiguity).
- **Order-ledger reconciliation** — cross-checks the proven slice against your order ledger
  (uncredited / missing / duplicate / refund-not-reflected).
- **Postable journal entries** — the reconciled slice exported as a balanced double-entry journal in
  **Tally Prime XML** (`<ENVELOPE>` voucher import) and clean JSON: gross → MDR fee → 18% GST ITC → bank,
  each voucher balancing to zero. Convention-agnostic (detects GST-inside-fee vs tax-separate per
  settlement). The JSON always carries every reconciled voucher; the Tally XML requires a voucher date, so
  a voucher whose source rows carry no `settled_at`/`created_at` date is omitted from the XML rather than
  emitted with an invalid empty date. (Reconcile against the JSON for the complete set.)
- **Proof Packets** — a per-credit evidence receipt (JSON/CSV) for every verdict; the whole run is auditable.
- **Close certificate + independent verifier** — the run seals into a content-hashed certificate (also
  ECDSA-signed when the optional `cryptography` extra and a signing key are configured), and a standalone
  verifier (`/verify` page + `verify_report`) independently re-checks it: the content hash, the signature
  (when present), the per-credit proof packets, and internal metric consistency — *without trusting
  untangle*. It confirms the certificate is authentic and self-consistent; it does not re-audit your bank
  against reality.
- **An adversarial challenger** — a counterfactual engine that, before accepting a Razorpay verdict, tries
  to *disprove* it and computes a proof margin, abstaining when a competing explanation is too close. It
  knows when *not* to act. *(Wired and tested; enabled once a benchmark with real false-positives certifies
  a margin threshold — on the current benchmark precision is already 1.000, so it stays inactive.)*
- **Active Recovery Controller** — turns abstentions and unresolved credits into an actionable recovery
  plan. Recommends ranked next-best actions by expected recoverable impact per unit cost (`export_settlement_report`,
  `confirm_utr_with_bank`, `provide_settlement_ids`, `classify_counterparty`). Amounts are framed honestly
  as "up to ₹X if confirmed", never "owed". Includes `resolve_delta` to track newly-resolved credits and
  recovered paise across reruns.
- **Agentic Exception-Investigation Loop** — when a credit is matched or leaning but its money does not
  tie out (`unbalanced_residual`, `partial_or_duplicate_settlement`, `reconstructed_split_leg`, `razorpay_coverage_not_found`),
  the engine autonomously diagnoses the root cause (`mdr_fee_drift`, `cross_cycle_refund_lag`, `on_hold_release`,
  `dispute_deduction`, `partial_capture`, `bank_charge_or_rounding`, `rolling_reserve`, or strictly `unexplained`),
  outputs an auditable step-by-step reasoning trace, preserves the negative space of evaluated candidates, and drafts a
  balanced corrective double-entry journal proposal.
- **Model Context Protocol (MCP) Server (Local Stdio & Remote Streamable-HTTP)** — exposes 10 read-only
  tools (`reconcile_files`, `list_unresolved_cash`, `explain_bank_credit`, `get_competing_explanations`,
  `suggest_next_evidence`, `export_proof_packet`, `verify_proof_packet`, `generate_close_certificate`,
  `export_journal_entries`, `investigate_variance`) to desktop AI agents over stdio (`untangle-mcp`), and
  hosted agents (ChatGPT, claude.ai, Claude Code) over remote streamable-HTTP mounted at `/mcp` with **zero
  local installation**. 100% read-only and analytical — never mutates state or moves money. Full guide:
  [`docs/MCP.md`](docs/MCP.md).
- **Global Evidence-Constrained Solver** — formulates whole-period reconciliation as a single constrained
  assignment problem over a candidate graph, minimizing invalid picks, unexplained paise, and ops cost.
  Reconciles globally consistent assignments and rejects locally-plausible matches that violate global settlement
  uniqueness (e.g. credit A cannot take settlement S when S is uniquely consumed by B+C). When enabled
  (`--global-solver`), sealed holdout recall improves from **0.839 to 0.857** (+2 reconciled settlements) at
  **1.000 precision** and **0 decoy false-positives** (reproduce via `python -m eval.sealed --compare-solver`).
  Gated behind a default-OFF flag (`global_solver=False`) preserving byte-identical baseline output.

## Measured — precision first, never a bare match rate

On a sealed, generator-blind adversarial holdout (n ≈ 294, 14 narration-corruption modes):

- **Razorpay attribution precision: 1.000** — zero false "this is Razorpay's".
- **0 decoy false-positives** across 181 look-alike non-Razorpay credits.
- **Recall 0.91** on true Razorpay credits (0.84 on the blind sealed set) — the rest abstain, never guessed.
- **±₹0 residual** on every reconciled credit; unresolved credits are surfaced, not forced.
- **Global solver (optional, `--global-solver`)**: sealed holdout recall improves from **0.839 to 0.857** (+2 reconciled settlements) at **1.000 precision** and **0 decoy false-positives** (`python -m eval.sealed --compare-solver`).

Honest scope: these are measured on a labelled adversarial benchmark, **not** a claim about every
real-world statement. On your own unlabelled upload, untangle shows attributed-vs-abstained counts and a
real coverage curve, and never asserts a precision it cannot measure.

The evaluator also reports a deterministic 95% confidence interval for each labelled precision
and recall, with the numerator and denominator (for example, `x/n`, where `n` is that metric's
labelled denominator). The interval is a **cluster bootstrap keyed by the underlying settlement
event**: split settlements emit several correlated bank legs from one event, so treating each leg
as an independent Bernoulli trial (as a plain Wilson/Wald interval would) understates uncertainty
and cannot honestly be called 95%. Resampling whole settlement events instead propagates that
correlation into the interval width; a fixed seed keeps it reproducible. A zero denominator is
reported as unavailable, not as a measured zero. These intervals describe uncertainty in this
labelled synthetic benchmark only; they are not production guarantees under distribution shift and
are never shown as performance for an unlabelled upload.

## Quickstart

untangle is a real product, not a demo — upload your **own** three files and get a real reconciliation.
The bundled sample just lets you see it work instantly. The **same web app** runs two ways — on your own
machine, or hosted on the web — with identical behaviour: landing, upload, live reconcile, and a JSON API.

### Option A — Run it on the web (hosted, one click)

The full product is a single self-contained FastAPI app that deploys anywhere Docker runs. On
[Render](https://render.com): **New → Blueprint → point at this repo** — it reads [`render.yaml`](render.yaml),
builds the [`Dockerfile`](Dockerfile), and gives you a public URL serving the complete app (free tier is
enough for the demo). No config, no database, no keys stored. Full walkthrough: [`docs/DEPLOY.md`](docs/DEPLOY.md).

> **Hosted demo:** deployment is planned; no public URL is claimed yet. Until then, run the local
> quickstart below. Do not upload sensitive financial data to an unverified third-party deployment.

### Option B — Run it locally

```bash
git clone https://github.com/vinayaksonthalia/untangle && cd untangle
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"

# generate the seeded sample dataset (byte-identical across runs)
python3 -m generator.generate --seed 42 --scale 1.0 --out data

# run the web app  →  http://localhost:8080
uvicorn webapp.app:app --port 8080
```

Both options serve the same routes:
`/` landing · `/app` upload your three files · `/try-sample` instant sample run · `/api/docs` the JSON API.

`/try-sample` and `/reconcile` return a no-store bootstrap page which places the bounded result bundle in browser-tab `sessionStorage` before navigating to `/dashboard`. Results persist across refreshes and are normally cleared when the tab closes (browser session restore can retain them); no private raw inputs or result database is retained by the server. Legacy `/api/*/current` endpoints return `410 Gone`.

- **Bring your own data:** a bank statement CSV (`value_date · narration · credit · debit`), the Razorpay
  settlement report JSON (`entity_id · type · amount · fee · tax · settlement_utr`), and your order ledger
  CSV (`order_id · amount_paise · status`). Processed in a per-request temp directory and deleted the
  moment the report renders — nothing is persisted (locally or hosted).

### Option C — Headless CLI (no web)

```bash
python -m engine.cli run --bank data/bank_statement.csv --recon data/recon_report.json \
  --ledger data/order_ledger.csv --out out/
```

### Option D — Remote MCP for AI Agents (ChatGPT / claude.ai / Claude Code)

Connect hosted or local agents directly to untangle's 10 read-only tools:
- **Hosted Agent URL (zero local install):** `https://<your-app-url>/mcp` (e.g. `https://untangle.onrender.com/mcp`)
- **Local Desktop MCP (Claude Desktop / Cursor):** `untangle-mcp` (stdio)
- **Local HTTP MCP:** `untangle-mcp --http --port 8081`

Full instructions & tool schemas: [`docs/MCP.md`](docs/MCP.md).

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
                            │
                            ▼
         POST TO BOOKS: balanced journal (Tally XML + JSON)
         + content-hashed close certificate (signed when configured) → independently verifiable
```

Every step is deterministic and read-only toward money. The intelligence is in the judgment: tiered
evidence (A: exact UTR · B: scored weak evidence · C: bounded set-sum), calibrated abstention, and an
adversarial challenger that tries to disprove each verdict before accepting it.

## Repository layout

```
engine/       attribution, proof-gate, reconciliation, split reconstruction, ledger, proof packets
generator/    seeded multi-rail synthetic data + blind ground-truth labels (no matcher logic)
eval/         evaluation harness, sealed holdout runner, 15 MiB stress benchmark, calibration
webapp/       FastAPI app — landing, upload, live reconcile, JSON API
ui/           the dashboard renderer
specs/        spec-driven development trail (constitution → spec → plan → tasks per feature)
docs/         ARCHITECTURE, BENCHMARK, DEPLOY, EXCEPTION_TAXONOMY, EXPLAINED, and more
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

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

Contributions are welcome. Read the [contributing guide](CONTRIBUTING.md),
[Code of Conduct](CODE_OF_CONDUCT.md), and [security policy](SECURITY.md) before participating.

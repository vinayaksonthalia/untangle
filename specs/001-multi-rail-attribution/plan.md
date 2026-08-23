# Implementation Plan: Multi-Rail Credit Attribution & Razorpay-Slice Reconciliation

**Branch**: `001-multi-rail-attribution` | **Date**: 2026-08-23 | **Spec**: [spec.md](./spec.md)

## Summary

Attribute every bank-statement credit to its payment rail, then reconcile only the
Razorpay slice and surface recoverable fee-GST. The engine is a deterministic
evidence-combining classifier with calibrated abstention; a language model is used only
to interpret ambiguous free-text narrations the deterministic tiers leave as UNKNOWN.
Everything is measured against blind ground truth, per rail and per hard-case class,
with a no-AI ablation. Delivered as a Python CLI producing reproducible JSON/console
reports. UI is a separate later feature.

## Technical Context

**Language/Version**: Python 3.12+ (matches the existing generator and eval tooling)

**Primary Dependencies**: stdlib-first. Justified additions only: `hypothesis` (property-based tests). LLM tier uses the stdlib HTTP client against an OpenAI-compatible endpoint — no heavy SDK. No pandas unless a measured need appears.

**Storage**: Files only — reads `data/*.json|csv`; writes reports to `out/` and an append-only JSONL audit ledger. No database.

**Testing**: `pytest` + `hypothesis` for conservation invariants; the eval harness doubles as an integration test; seeded, deterministic.

**Target Platform**: Linux/macOS CLI.

**Project Type**: Single project (CLI library + eval harness).

**Performance Goals**: Process a 10k+ recon-row / ~300 bank-line batch end-to-end (deterministic path) in seconds; report p50/p95 latency and LLM cost per 1,000 rows for the AI path.

**Constraints**: Deterministic and seeded (byte-identical reports for identical inputs on the no-AI path); read-only toward money; secrets only from gitignored `.env`; PII masked before any LLM call; engine must not import `generator/`.

**Scale/Scope**: One merchant-account batch per run; ~300 bank credits over ~12k settled transactions at default scale.

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1.*

| Principle | How this plan complies |
|---|---|
| I. Honesty & Measurement | Eval reports per-rail AND per-hard-case precision/recall vs blind ground truth; no blended headline; every schema claim already cited in `scripts/verify_schema_claims.py`. |
| II. Deterministic core, AI at edges | Tiers A–C are deterministic; LLM only on residual UNKNOWN narrations and never issues a money verdict alone; `--no-ai` runs the whole pipeline and the ablation reports its marginal value. |
| III. Test-first & property-based | Conservation invariants written as `hypothesis` properties before/with the engine; generator/matcher isolation enforced (engine never imports `generator/`, reads only `data/` + taxonomy). |
| IV. Security & least privilege | No write/payout scopes; read-only; PII masked pre-LLM; abstain (UNKNOWN) over a wrong attribution; append-only hash-chained audit ledger. |
| V. Professional craft | CLI with clean errors, all states handled, one-command reproducible run, documented reports. UI deferred to its own feature (not skipped — sequenced). |

**Result: PASS** (no violations; no complexity requiring justification).

## Project Structure

### Documentation (this feature)
```text
specs/001-multi-rail-attribution/
├── plan.md            # this file
├── research.md        # Phase 0 decisions
├── data-model.md      # Phase 1 entities
├── contracts/cli.md   # Phase 1 CLI contract
├── quickstart.md      # Phase 1 validation guide
└── tasks.md           # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)
```text
engine/
├── __init__.py
├── ingest.py        # load + validate the 3 artifacts; derive stable per-line key
├── evidence.py      # per-rail signals: UTR, narration patterns, amount/date correlation
├── attribute.py     # tiers A/B/C → rail verdict | UNKNOWN + confidence + evidence trail
├── abstain.py       # cost-model threshold; calibration
├── llm/
│   ├── client.py    # provider-agnostic OpenAI-compatible client (env-driven); --no-ai aware
│   ├── mask.py      # PII masking before any call
│   └── narrate.py   # residual-narration resolution (proposes; rules confirm)
├── reconcile.py     # Razorpay-slice coverage (set-sum) + paise conservation
├── feegst.py        # recoverable fee-GST from recon's own fee+tax
├── exceptions.py    # taxonomy-coded exception list
├── explain.py       # "why is this credit (not) matched?" trace
├── audit.py         # append-only hash-chained ledger
└── cli.py           # entry point → JSON/console reports

eval/
├── harness.py       # per-rail + per-hard-case P/R, calibration, ablation, throughput/cost
└── metrics.py       # scoring vs BLIND ground truth (loaded only by eval, never by engine)

tests/
├── unit/            # per-module deterministic tests
├── property/        # hypothesis conservation invariants
└── integration/     # end-to-end on a generated batch
```

**Isolation rule (constitution III):** nothing under `engine/` imports from `generator/`. The engine consumes only `data/*` outputs and `EXCEPTION_TAXONOMY.md`. The blind ground truth (`data/ground_truth.json`) is read only by `eval/`, never by `engine/`.

## Phase 0 — Research
See [research.md](./research.md): language/deps, matching algorithm per tier, abstention cost model, calibration method, LLM provider strategy, audit anchoring.

## Phase 1 — Design
See [data-model.md](./data-model.md) (entities), [contracts/cli.md](./contracts/cli.md) (CLI + report contracts), [quickstart.md](./quickstart.md) (end-to-end validation).

**Post-design Constitution re-check: PASS** — design keeps deterministic core, isolation, and measurement intact.

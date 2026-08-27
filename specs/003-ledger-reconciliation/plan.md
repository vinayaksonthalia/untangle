# Implementation Plan: Order-Ledger Reconciliation

**Branch**: `003-ledger-reconciliation` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

## Summary

Make the merchant's order ledger — currently validated on ingest but unused — a real input to
reconciliation. A thin, deterministic module cross-checks the *proven Razorpay slice* (already
produced by `reconcile()`) and the settlement report against the ledger, and emits a new, separable
class of honest exceptions (`uncredited_order`, `ledger_mismatch`, `duplicate_order_booking`,
`refund_not_reflected`). It is strictly **additive**: it never changes an attribution or
reconciliation verdict, and the run's precision/recall/reconciled/fee-GST numbers are unchanged.
Precision-first — it abstains (surfaces for review) rather than assert a wrong order↔settlement link.

## Technical Context

**Language/Version**: Python ≥3.12 (matches the engine). Stdlib-first; **no new runtime dependencies**.
**Primary inputs**: `list[OrderLedgerEntry]` (order_id, amount_paise, status, created_at) + the
existing `reconcile()` outputs (`SettlementIndex`, `list[ReconciliationResult]`, `recon_rows`).
**Join key**: `order_id` — present on both `OrderLedgerEntry` and `ReconRow` (`ReconRow.order_id`).
**Primary output**: `list[ExceptionRecord]` (reusing the existing model), merged into the report's
exception queue and rendered in the dashboard.
**Testing**: pytest + property-style invariants (additive/no-verdict-change; determinism; empty-ledger
safety), plus crafted-batch unit tests for each reason code.
**Target**: the existing `engine/` library + `webapp`/`ui` surfaces; CLI `run` already loads the ledger.
**Constraints**: read-only (no money movement, no ledger writes); deterministic/reproducible; exact-paise
comparisons within the engine's existing ±₹1 labelled drift tolerance; must not error on a missing/empty ledger.
**Scope/Scale**: order↔settlement discrepancy detection only — NOT a general accounting/journal/tax tool.

**No NEEDS CLARIFICATION**: the three ambiguous axes (join key, status vocabulary, tolerance) are
resolved in [research.md](./research.md) with documented defaults.

## Constitution Check

| Principle | How this feature complies |
|---|---|
| I. Honesty & Measurement | Every exception cites the exact ledger row(s) and settlement/recon reference compared; nothing is asserted without provable evidence. The additive-invariance is itself a test (SC-003). |
| II. Deterministic Core, AI at Edges | 100% deterministic rule-based joins/arithmetic. No LLM anywhere in this feature. |
| III. Test-First & Property-Based | Property tests: (a) turning the feature on never changes any attribution/reconciliation verdict or headline metric; (b) same inputs → same exceptions; (c) empty/missing ledger → zero exceptions, no error. Written before/with the implementation. |
| IV. Security & Least Privilege | Read-only: no writes to the ledger, no money movement, no new scopes. Abstains on ambiguity (never asserts a wrong link). Ledger data already ingested; no new PII surface. |
| V. Professional Craft | New reason codes documented in `contracts/` and `EXCEPTION_TAXONOMY.md`; dashboard surface designed (grouped, evidence-bearing); kind handling of malformed/absent ledger. |

**Gate: PASS** — no violations; no complexity deviations to justify.

## Project Structure

### Documentation (this feature)

```
specs/003-ledger-reconciliation/
├── spec.md              # done
├── plan.md              # this file
├── research.md          # decisions (join key, status vocabulary, tolerance, abstain rules)
├── data-model.md        # entities + the ExceptionRecord reuse
├── contracts/
│   └── ledger-exceptions.md   # the new reason codes: meaning, evidence, suggested action
├── quickstart.md        # runnable validation scenarios
└── checklists/requirements.md # done (green)
```

### Source Code (repository root)

```
engine/
├── ledger.py            # NEW — reconcile_ledger(ledger, reconciliations, recon_rows, sindex) -> list[ExceptionRecord]
├── cli.py               # wire ledger exceptions into build_report (merge into the exception list)
├── exceptions.py        # (reason-code labels already centralized; add the 4 new codes to the taxonomy map)
└── models.py            # ExceptionRecord reused as-is; no model change expected
ui/
└── dashboard.py         # add the 4 reason labels/colors; the queue already renders any ExceptionRecord
tests/
├── unit/test_ledger.py            # per-reason-code crafted-batch tests
└── property/test_ledger_additive.py  # invariance + determinism + empty-ledger safety
docs/
└── EXCEPTION_TAXONOMY.md          # document the 4 new classes
```

**Structure decision**: single-project library (engine/) + its existing web/ui surfaces — matches the
current layout. The feature is one new thin module (`engine/ledger.py`) plus wiring and docs.

## Complexity Tracking

No constitution deviations. The one bounded risk — a *false* order↔settlement link — is handled by
FR-005 (abstain on anything not provable to the exact paise on a shared id), mirroring the proof-gate
discipline already proven in the attribution engine.

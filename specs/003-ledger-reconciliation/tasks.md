---
description: "Task list for Order-Ledger Reconciliation (Feature 003)"
---

# Tasks: Order-Ledger Reconciliation

**Input**: Design documents from `specs/003-ledger-reconciliation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ledger-exceptions.md
**Tests**: INCLUDED — the constitution mandates test-first / property-based for money paths.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no incomplete-dependency)
- **[Story]**: US1 (uncredited order, P1), US2 (mismatch + duplicate, P2), US3 (refund, P3)

---

## Phase 1: Setup

- [ ] T001 Create `engine/ledger.py` with the module docstring, the recognised-status constants (from research.md Decision 2), and a `reconcile_ledger(ledger, reconciliations, recon_rows, sindex) -> list[ExceptionRecord]` stub that returns `[]`. Import `ExceptionRecord`/`EvidenceItem` from `engine.models`; no new deps.
- [ ] T002 [P] Create empty test files `tests/unit/test_ledger.py` and `tests/property/test_ledger_additive.py` with imports and shared crafted-batch helpers (a tiny `_ledger(...)`, `_recon_rows(...)`, and a helper to run `attribute_all → reconcile → reconcile_ledger`).

---

## Phase 2: Foundational (blocks all stories)

- [ ] T003 [US-] In `engine/ledger.py`, build the in-memory indices from the inputs (data-model.md): `settled_order_ids` (order_ids covered by a *reconciled* settlement), `ledger_by_order_id`, `settled_amount_by_order_id` (sum of the order's settlement contribution), and `refunded_order_ids` (order_ids whose settlement carries a refund `type` or a `dispute_id`). Pure, deterministic; helper functions, no verdict feedback.
- [ ] T004 [US-] **Additivity property test FIRST** in `tests/property/test_ledger_additive.py`: run the full pipeline on the seeded batch, capture headline totals (razorpay precision/recall, reconciled count, fee-GST); assert `reconcile_ledger(...)` returns only `ExceptionRecord`s and that appending them changes NONE of those totals (SC-003). Also: determinism (same inputs → identical stably-ordered list) and empty/missing ledger → `[]`, no error (SC-005). These must pass by construction (pure function).
- [ ] T005 [US-] Wire into `engine/cli.py build_report`: call `reconcile_ledger(...)` and **append** its records to the exceptions list (after `build_exceptions`), updating `exception_count`/`exceptions_by_reason`. Guard: never call it in a way that could alter attributions/reconciliations. Stable ordering by `(reason_code, line_key)`.

**Checkpoint**: pipeline runs with a no-op-safe ledger step; additivity locked by test.

---

## Phase 3: User Story 1 — Uncredited orders (P1) 🎯 MVP

**Goal**: surface paid orders with no reconciled Razorpay settlement (`uncredited_order`).
**Independent Test**: a crafted batch with a paid, un-settled order yields exactly one `uncredited_order`; a paid order covered by a reconciled settlement yields none.

- [ ] T006 [P] [US1] Unit test in `tests/unit/test_ledger.py`: (a) paid order absent from `settled_order_ids` → one `uncredited_order` with order_id/amount/evidence/suggested_action; (b) paid+settled order → none; (c) id match but amount out of tolerance → NOT `uncredited_order` (deferred to US2 mismatch) — abstain from the clean-link claim.
- [ ] T007 [US1] Implement the `uncredited_order` detector in `engine/ledger.py`: for each ledger order in a believed-paid status whose `order_id` ∉ `settled_order_ids`, emit an `ExceptionRecord` per contracts/ledger-exceptions.md. Ignore unknown-status and id-less rows (never assume paid).

**Checkpoint**: US1 fully functional and independently testable (the MVP — "money possibly owed").

---

## Phase 4: User Story 2 — Missing / mis-booked settlement orders (P2)

**Goal**: `ledger_mismatch` (missing / contradicting status / out-of-tolerance amount) and `duplicate_order_booking`.
**Independent Test**: a reconciled settlement whose order is missing/contradicted in the ledger → `ledger_mismatch`; a doubly-booked order_id → `duplicate_order_booking`.

- [ ] T008 [P] [US2] Unit tests in `tests/unit/test_ledger.py`: settlement order missing from ledger → `ledger_mismatch (missing)`; present but contradicting status → `ledger_mismatch (status)`; present but amount beyond ±₹1 → `ledger_mismatch (amount)`; same order_id twice → `duplicate_order_booking`.
- [ ] T009 [US2] Implement the `ledger_mismatch` detector: for each reconciled settlement's order_id, compare against the ledger row (absent / contradicting status / out-of-tolerance amount) and emit with observed-vs-expected evidence.
- [ ] T010 [US2] Implement the `duplicate_order_booking` detector: order_ids where `len(ledger_by_order_id[oid]) > 1` and the id maps to a single settled payment → emit both rows as evidence.

**Checkpoint**: US1+US2 both independently pass.

---

## Phase 5: User Story 3 — Refunds/chargebacks not reflected (P3)

**Goal**: `refund_not_reflected`.
**Independent Test**: a settlement carrying a refund/dispute for an order the ledger still marks fully paid → one `refund_not_reflected`.

- [ ] T011 [P] [US3] Unit test in `tests/unit/test_ledger.py`: settlement refund/dispute for a still-fully-paid ledger order → `refund_not_reflected` with the refunded amount; a ledger order already marked refunded → none.
- [ ] T012 [US3] Implement the `refund_not_reflected` detector: order_id ∈ `refunded_order_ids` AND the ledger row is in a believed-paid (not refund/dispute) status → emit.

**Checkpoint**: all three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting

- [ ] T013 [P] Add the four reason-code labels + colours to `ui/dashboard.py` `_REASON` map (they already render in the exception queue and filter chips). Regenerate `ui/dashboard.html`.
- [ ] T014 [P] Document the four classes in `docs/EXCEPTION_TAXONOMY.md` (mirror contracts/ledger-exceptions.md).
- [ ] T015 Run the pipeline end-to-end (`engine.cli run` with the ledger) and confirm ledger exceptions appear; run `quickstart.md` scenarios A–E.
- [ ] T016 Full suite green (ruff, bandit, pytest incl. new unit + property tests); if any real defect was caught during the build, log it in `INCIDENTS.md`.

---

## Dependencies & Order

- Phase 1 → Phase 2 (foundational indices + additivity test + wiring) → Phase 3 (US1 MVP) → Phase 4 (US2) → Phase 5 (US3) → Phase 6 (polish).
- US1/US2/US3 detectors are independent (different functions, same module) once Phase 2 indices exist.
- Additivity/determinism/empty-ledger property test (T004) is the guardrail for every later task.

## MVP scope

**User Story 1 alone (uncredited orders)** is a shippable MVP — it surfaces *money the merchant may be owed*, the single highest-value output. US2/US3 add books-integrity depth.

## Notes

- Every detector is a pure function of already-computed outputs — it never feeds back into attribution/reconciliation (additivity).
- Abstain over guess: no clean order↔settlement link is asserted without an id match AND amount agreement within ±₹1.
- Read-only: no writes, no money movement.

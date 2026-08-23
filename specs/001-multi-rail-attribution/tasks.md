---
description: "Task list — Multi-Rail Credit Attribution (untangle, feature 001)"
---

# Tasks: Multi-Rail Credit Attribution & Razorpay-Slice Reconciliation

**Input**: Design docs in `/specs/001-multi-rail-attribution/` (plan, spec, research, data-model, contracts/cli, quickstart)

**Tests**: INCLUDED — constitution III mandates test-first & property-based; spec FR-015 mandates blind-ground-truth eval.

**Isolation (constitution III)**: nothing under `engine/` may import from `generator/`. `data/ground_truth.json` is read only by `eval/`, never by `engine/`. This must be enforced by a test (T009).

## Format: `[ID] [P?] [Story] Description`
- **[P]** = parallelizable (different files, no incomplete deps). **[US#]** = user story.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create source tree per plan.md: `engine/`, `engine/llm/`, `eval/`, `tests/unit/`, `tests/property/`, `tests/integration/` (with `__init__.py` where needed)
- [ ] T002 Add `pyproject.toml` (Python 3.12+, deps: `pytest`, `hypothesis`; stdlib-first otherwise) and a `Makefile`/`README` run targets
- [ ] T003 [P] Configure `ruff` (lint+format) and a `pytest.ini`/`pyproject` test config
- [ ] T004 [P] Generate the working dataset: `python3 -m generator.generate --seed 42 --scale 1.0 --out data` (input to everything downstream)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ No user-story work begins until this phase is done.**

- [ ] T005 Define serializable dataclasses in `engine/models.py` per data-model.md (BankCreditLine, ReconRow, OrderLedgerEntry, RailAttribution, EvidenceItem, ReconciliationResult, FeeGstRecovery, Exception, RunReport). Money as int paise.
- [ ] T006 Implement `engine/ingest.py`: load + schema-validate the three artifacts; derive the stable per-line key = hash(value_date, amount_paise, narration, bank_ref); NEVER use the generator's `line_id`. Clear what/why/fix errors (exit 2).
- [ ] T007 [P] Implement `engine/audit.py`: append-only JSONL hash-chained ledger (each entry hashes the previous); expose the chain-head root.
- [ ] T008 [P] Implement `engine/llm/mask.py` (PII masking: names/emails/phones → placeholders) and `engine/llm/client.py` (provider-agnostic OpenAI-compatible client; provider+model+key from env; `--no-ai` short-circuits to a no-op returning UNKNOWN).
- [ ] T009 [P] Isolation guard test in `tests/unit/test_isolation.py`: assert no module under `engine/` imports `generator`, and that `engine/` never reads `data/ground_truth.json` (static scan).
- [ ] T010 Config/env loader in `engine/config.py`: read `.env` (gitignored), expose provider/model/threshold/seed; error (exit 3) if AI requested but no key.

**Checkpoint**: models + ingest + audit + LLM skeleton + isolation guard ready.

---

## Phase 3: User Story 1 — Attribute every bank credit to its rail (Priority: P1) 🎯 MVP

**Goal**: Each bank credit → rail verdict | UNKNOWN with confidence + evidence, abstaining on weak signal.
**Independent Test**: run attribution on the generated batch; `eval` reports per-rail AND per-hard-case precision/recall vs blind ground truth, with decoy false-positive rate and calibration.

### Tests for User Story 1 (write first, must fail before impl)
- [ ] T011 [P] [US1] Property test `tests/property/test_attribution_conservation.py`: every BankCreditLine gets exactly one verdict; idempotent re-run (`--no-ai`) is byte-identical.
- [ ] T012 [P] [US1] Unit tests `tests/unit/test_evidence.py`: each signal (utr_exact, narration_pattern, amount_corr, value_date_proximity) fires on crafted rows and stays silent otherwise.
- [ ] T013 [P] [US1] Eval-scoring unit test `tests/unit/test_metrics.py`: per-rail + per-hard-case P/R and calibration bins compute correctly on a tiny fixture.

### Implementation for User Story 1
- [ ] T014 [P] [US1] `engine/evidence.py`: per-rail signals — UTR match vs recon `settlement_utr`, per-rail narration patterns, amount correlation vs settlement nets, value-date proximity; each returns weighted EvidenceItems.
- [ ] T015 [US1] `engine/attribute.py` Tier A (exact evidence) + Tier B (scored weak-evidence combination) → rail | UNKNOWN + confidence + evidence trail (depends on T014).
- [ ] T016 [US1] `engine/attribute.py` Tier C: bounded set-sum correlation for split/merge/carry-forward candidates, constrained by settlement grouping; abstain on ambiguity (depends on T015).
- [ ] T017 [US1] `engine/abstain.py`: cost-model-derived threshold τ; below τ → UNKNOWN; expose precision/coverage curve data (depends on T015).
- [ ] T018 [US1] `engine/llm/narrate.py`: on residual UNKNOWN narrations only, PII-masked, propose a rail; deterministic rules confirm before the verdict stands; record `llm_used` (depends on T008, T015).
- [ ] T019 [US1] `engine/cli.py` `run` command → RailAttribution set + console summary + `out/report.json` (attribution sections); writes audit entries (depends on T015–T018).
- [ ] T020 [US1] `eval/metrics.py` + `eval/harness.py`: score vs blind ground truth — per-rail & per-hard-case P/R, decoy FP rate, calibration; `--ablation` (AI on/off delta + cost/1k + p50/p95) (depends on T019).

**Checkpoint**: attribution works and is measured; MVP demoable (naive baselines fail where this doesn't — cross-ref generator/difficulty_probe.py).

---

## Phase 4: User Story 2 — Reconcile the Razorpay slice & recover fee-GST (Priority: P2)

**Goal**: For razorpay_settlement credits, resolve covered recon rows (paise-exact) and report recoverable fee-GST from Razorpay's own tax-on-fee.
**Independent Test**: each reconciled credit's covered net sums to the credit to the paise; fee-GST equals Σ recon `tax` over reconciled txns, per-txn traceable.

### Tests for User Story 2
- [ ] T021 [P] [US2] Property test `tests/property/test_reconcile_conservation.py`: Σ(reconciled)+Σ(exceptions)+Σ(non-rzp attributed) = Σ(all credits); no recon row double-covered.
- [ ] T022 [P] [US2] Unit test `tests/unit/test_feegst.py`: fee-GST aggregation equals Σ recon `tax` on a fixture; traceable by entity_id.

### Implementation for User Story 2
- [ ] T023 [US2] `engine/reconcile.py`: for razorpay_settlement credits resolve covered entity_ids (set-sum within settlement/date window), compute residual, flag balanced; feed unresolved → exceptions (depends on T016).
- [ ] T024 [US2] `engine/feegst.py`: sum recon `tax_paise` over reconciled txns; per-entity breakdown; rupee total (depends on T023).
- [ ] T025 [US2] Extend `engine/cli.py` report with reconciliation + fee-GST sections and console rupee headline (depends on T023, T024).

**Checkpoint**: US1 + US2 both independently functional; rupee headline present.

---

## Phase 5: User Story 3 — Honest exceptions & "why" trace (Priority: P2)

**Goal**: Every unresolved credit in a taxonomy-coded exception list; a `why <line_key>` command returns the full evidence trail.
**Independent Test**: keyless adjustment credit lands in exceptions (never force-matched); `why` returns verdict+confidence+evidence (+coverage if reconciled).

### Tests for User Story 3
- [ ] T026 [P] [US3] Unit test `tests/unit/test_exceptions.py`: each unresolved class maps to the correct EXCEPTION_TAXONOMY reason_code.
- [ ] T027 [P] [US3] Integration test `tests/integration/test_why_trace.py`: `why` returns a complete, correct trace for a known line.

### Implementation for User Story 3
- [ ] T028 [US3] `engine/exceptions.py`: build exception list with taxonomy reason_code + suggested_action for every non-auto-resolved credit (depends on T017, T023).
- [ ] T029 [US3] `engine/explain.py` + `engine/cli.py` `why` command: reconstruct the trace for one line from stored attribution/audit (depends on T019, T028).

**Checkpoint**: all three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting

- [ ] T030 [P] Full integration run `tests/integration/test_end_to_end.py`: quickstart steps 3–4 pass; conservation PASS; `--no-ai` report byte-identical across runs.
- [ ] T031 [P] Benchmark LLM providers (ox-alpha/gemini/groq/cerebras) on the narration task; record chosen model + numbers in `docs/llm-benchmark.md` (AI-judgment evidence).
- [ ] T032 [P] Update `README.md` (real usage + results), write `docs/ARCHITECTURE.md`, refresh `generator/`↔engine data flow.
- [ ] T033 Throughput + cost: p50/p95 latency and LLM cost per 1,000 rows in the eval output.
- [ ] T034 Run `scripts/verify_schema_claims.py` + full `pytest` green; then an Opus review pass of the engine before it's called done.
- [ ] T035 Vinayak writes `INCIDENTS.md` entries for real failures hit during implementation (human-authored, per constitution).

---

## Dependencies & Execution Order
- Setup (P1) → Foundational (P2) blocks all stories → US1 (P1) → US2/US3 (P2, may parallelize after US1's attribution exists) → Polish.
- Within a story: tests fail first → models → services → CLI/report.
- US2 and US3 both depend on US1 attribution (T015–T017) but are independent of each other after that.

## Parallel Opportunities
- Setup T003/T004; Foundational T007/T008/T009; US1 tests T011–T013; US1 evidence T014; US2 tests T021/T022; US3 tests T026/T027; Polish T030–T032.

## Implementation Strategy
- **MVP = Phases 1+2+3 (US1)**: attribution measured against blind ground truth. Stop, validate, demo.
- Then US2 (rupee headline), then US3 (exceptions+why), then Polish.
- Commit after each task or logical group; daily push (private).

## Notes
- Enforce isolation (T009) — it protects every reported number.
- Precision-first: a wrong auto-attribution is worse than an abstention.
- Never send real merchant data to a prompt-retaining model (research R5).

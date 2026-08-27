# Feature 005 — Active Recovery Controller · PHASE PLAN (Antigravity build brief)

**This is a self-contained brief. Build it exactly as specified. Claude reviews + commits each phase and
fixes any Qodo review findings.** Roadmap item #2 (see `specs/004-.../STATUS.md`, `memory/intelligence-roadmap`).

---

## 0. What this feature is (and is NOT)

untangle already **abstains** rather than guess: unresolved bank credits go to an exception queue with a
`reason_code` + a `suggested_action` (see `engine/models.py:ExceptionRecord`, `engine/exceptions.py`).
Today those suggestions are static, per-credit, and unranked.

**The Active Recovery Controller turns abstention into an intelligent, ranked recovery plan.** For every
unresolved credit it diagnoses *why* it couldn't be proven, enumerates *what evidence would resolve it*,
groups credits that the *same* action would resolve, and ranks the recommended **next-best actions by
expected recoverable impact per unit cost**. It is the "failure recovery" story: untangle doesn't just say
"I can't prove this" — it says *"here is the single highest-value thing to do next, and it would resolve
₹X across N credits."*

**Hard constraints (non-negotiable — these are the constitution):**
- **Deterministic. No LLM anywhere in the decision path.** Pure functions over already-computed outputs.
- **Additive.** It must NOT change any attribution, reconciliation, GST, or the headline metrics
  (precision 1.000, recall, reconciled count, fee-GST). A property test locks this.
- **Read-only toward money.** No writes, no money movement, no feedback into attribution/reconciliation.
- **Precision-first / honest.** It **recommends** an action; it never **asserts** a credit is resolved or
  that money is owed. Amounts are framed "up to ₹X *could* be recovered **if** this evidence confirms the
  tie" — never "₹X is owed."
- **Stdlib-only** (no new runtime deps). Fits the `engine/` layout and the `eval/` honesty conventions.

**Out of scope:** an interactive server-side loop / uploading follow-up files through the UI (the rerun is
just re-running the existing pipeline with better inputs); anything probabilistic that an LLM would decide.

---

## 1. Follow spec-driven development first (Phase 0 deliverable)

Before code, produce the spec-kit trail in `specs/005-active-recovery-controller/` mirroring Feature 004
(`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `checklists/requirements.md`,
`tasks.md`). Use this brief as the source of truth. Run the repo's `speckit-*` skills if available, else
author the files directly in the same structure/quality as `specs/004-adversarial-challenger/`.

---

## 2. Data model (new, in-memory only — `engine/recovery.py`)

```python
@dataclass(frozen=True)
class Hypothesis:
    line_key: str
    rail: str                 # the rail this credit MIGHT be (razorpay_settlement / other_gateway / ...)
    weight: float             # from the existing evidence scores (_combine); 0..1
    blocking_reason: str      # why it isn't proven (e.g. "mangled_utr", "no_settlement_row", "unknown_sender")

@dataclass(frozen=True)
class RecoveryAction:
    action_type: str          # from the taxonomy in §3
    params: dict              # e.g. {"date_from": "...", "date_to": "...", "entity": "..."}
    resolves: tuple[str, ...] # line_keys this action could resolve (sorted, deterministic)
    recoverable_paise: int    # SUM of the amounts of `resolves` (bounded, honest "up to")
    cost: float               # fixed operational weight from §3
    gain_per_cost: float      # recoverable_paise / cost  (the ranking key)

@dataclass(frozen=True)
class RecoveryPlan:
    actions: tuple[RecoveryAction, ...]   # ranked, highest gain_per_cost first (deterministic tie-break)
    unresolved_count: int
    unresolved_paise: int
    recoverable_if_actioned_paise: int    # sum over distinct resolvable credits (no double counting)
```

`ExceptionRecord` is reused, not replaced. `RecoveryPlan` is a new top-level section of the report.

---

## 3. Action taxonomy (grounded in untangle's ACTUAL abstention reasons)

Map each unresolved credit's `blocking_reason` (derived from its evidence + exception `reason_code`) to the
action(s) that would resolve it. Group credits that share an identical action (same type + params) into ONE
action. Costs are fixed weights (lower = cheaper/easier for the merchant).

| blocking_reason (derived) | RecoveryAction.action_type | params | cost |
|---|---|---|---|
| razorpay-leaning, has brand/`settlement_ref`/`ifsc_ratn` but no UTR/amount/set-sum tie | `export_settlement_report` | date window ±`_SPLIT_DATE_WINDOW` around the credit | 1.0 |
| razorpay-leaning, `utr_suffix_weak` only (UTR present but mangled/uncorroborated) | `confirm_utr_with_bank` | {date, amount_paise} | 2.0 |
| ambiguous set-sum (`multiple_satisfying_subsets`) | `provide_settlement_ids` | {date, amount_paise} | 1.5 |
| no distinctive signal (unknown rail, credit) | `classify_counterparty` | {date, amount_paise, bank_ref} | 0.5 |
| ledger exceptions (`uncredited_order`/`ledger_mismatch`) | `reconcile_order_ledger` | {order_id or settlement_id} | 1.0 |

- `blocking_reason` is derived deterministically from `razorpay_signals(line, index)` +
  `narration_rail_signals(line)` + the credit's `ExceptionRecord.reason_code` — do NOT invent new signals.
- `recoverable_paise` = sum of `line.amount_paise` over the action's `resolves` set. This is an **upper
  bound** ("up to"), never a claim of money owed. Say so in every human string.
- Ranking: sort by `gain_per_cost` desc, then `recoverable_paise` desc, then `action_type` asc (stable).
- Bound the work: cap actions emitted (e.g. top 20); if truncated, `log`/note it (no silent cap).

---

## 4. Phases (each is one commit; each must be green before the next)

### Phase 1 — Diagnosis & hypotheses  (`engine/recovery.py` + `tests/unit/test_recovery.py`)
- **T1.1** Create `engine/recovery.py` with the dataclasses (§2) and `diagnose(line, attribution, index,
  exception) -> list[Hypothesis]` — a pure function producing the competing hypotheses + `blocking_reason`
  for ONE unresolved credit, from its evidence and exception reason. No mutation.
- **T1.2 [test-first]** Unit tests: for each abstention reason (brand-no-tie, weak-suffix, ambiguous
  set-sum, unknown-sender, ledger exception) assert the expected `blocking_reason` and hypothesis rails/weights.
- **Acceptance:** deterministic; only reads inputs; hypotheses' weights come from the existing `_combine`.

### Phase 2 — Actions & info-gain ranking  (`engine/recovery.py`)
- **T2.1 [test-first]** Unit tests: crafted batches of unresolved credits → expected grouped, ranked
  `RecoveryAction`s (correct `resolves` grouping, `recoverable_paise` = summed amounts, `gain_per_cost`
  ordering, deterministic tie-break, top-N cap with a note).
- **T2.2** Implement `build_recovery_plan(lines, attributions, index, exceptions, *, max_actions=20)
  -> RecoveryPlan`: derive `blocking_reason` per unresolved credit, map to actions (§3), group by identical
  action, compute `recoverable_paise`/`cost`/`gain_per_cost`, rank, cap, and fill the plan summary
  (`unresolved_count/paise`, `recoverable_if_actioned_paise` counting each credit once).
- **Acceptance:** pure; a credit resolvable by two actions is counted once in
  `recoverable_if_actioned_paise`; every human string frames amounts as "up to … if confirmed".

### Phase 3 — Recovery trail & rerun diff  (`engine/recovery.py`)
- **T3.1 [test-first]** Tests: `resolve_delta(before, after)` given two report dicts (a run, then a rerun
  with better inputs) returns the set of `line_key`s newly resolved (abstained→attributed or newly
  reconciled) and the recovered paise. Deterministic; safe on identical inputs (empty delta).
- **T3.2** Implement `resolve_delta(before_report: dict, after_report: dict) -> dict` (the recovery trail
  step). No pipeline changes — the "rerun" is just calling the existing pipeline with new files.
- **Acceptance:** additive, read-only, deterministic.

### Phase 4 — Wiring & surfacing  (`engine/cli.py`, `ui/dashboard.py`, `engine/proof.py`)
- **T4.1** Wire into `build_report(cfg, lines, recon_rows, index, attributions, order_ledger=None)`: after
  exceptions are built, call `build_recovery_plan(...)` and attach it to the report as a new top-level
  `recovery_plan` section (guard: never alters attributions/reconciliations/metrics). Stable ordering.
- **T4.2 [property test]** `tests/property/test_recovery_additive.py`: run the full pipeline with and
  without the recovery step; assert every headline metric (razorpay precision/recall, reconciled count,
  fee-GST, attribution list) is **byte-identical**; determinism; empty/edge inputs safe.
- **T4.3** Dashboard: a "Recovery plan" panel in `ui/dashboard.py` — the ranked next-best actions, each
  showing the action, what it would resolve (N credits), and "up to ₹X recoverable if confirmed".
  Regenerate `ui/dashboard.html`. Add the recovery section to the CLI/JSON report + proof-packet surface.
- **Acceptance:** SC — headline metrics unchanged; dashboard renders the plan; JSON report carries it.

### Phase 5 — Docs & polish
- **T5.1** `docs/` note + a README "what you get" bullet (honest framing). `docs/EXCEPTION_TAXONOMY.md`
  cross-links the actions. Update `specs/005-.../` quickstart with the demo (§5).
- **T5.2** Full suite green (ruff, bandit, pytest incl. new unit + property); run the metric sweep and
  confirm precision 1.000 / recall unchanged; log any real defect caught during the build in `INCIDENTS.md`.

---

## 5. The 60-second demo (build toward this)
Upload a statement where 3 Razorpay credits have mangled UTRs and the settlement report is missing those
rows. untangle abstains on all 3, then the Recovery Plan says: **"Export the Razorpay settlement report for
Jan 3–5 — would resolve 3 credits, up to ₹Y, if the settlement rows confirm the tie."** Provide the fuller
report, re-run, and `resolve_delta` shows all 3 newly reconciled with the recovered paise. A weaker agent
just leaves them unexplained.

## 6. Invariants to assert (the guardrails)
- **Additive:** headline metrics byte-identical with/without the recovery step (property test).
- **Deterministic:** same inputs → identical plan (ordering stable).
- **Read-only / no feedback:** recovery never mutates `ReconIndex`, attributions, or reconciliations.
- **Honest:** amounts are "up to … if confirmed"; never "owed". Coverage/recoverable is never called precision.
- **No LLM:** the decision path is pure Python + fixed cost weights + the existing evidence scores.

## 7. Workflow
Build phase-by-phase, tests first where marked. After each phase: ensure ruff + the full pytest suite are
green. **Claude commits each phase separately and opens the PR; Qodo reviews; Claude fixes every finding.**
Do not batch all phases into one giant change — one coherent, green commit per phase.

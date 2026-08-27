# Feature 006 — Global Evidence-Constrained Reconciliation (the "global solver") · PHASE PLAN

**Self-contained Antigravity build brief. Build exactly as specified. Claude reviews + commits each phase
and fixes any Qodo findings.** Roadmap item #1 — the biggest moat. Build AFTER Feature 005 is merged.

---

## 0. What this is (and the one hard idea)

Today untangle decides mostly **per credit** (with a *local* global-conflict check already inside
`reconstruct_splits`). A locally-plausible match can be accepted even if it makes the rest of the month
impossible. **The global solver reconciles the WHOLE period as one constrained assignment**: it finds the
globally-consistent set of attributions and rejects any local match that no globally-valid solution can
support. *"This credit can't be that settlement, because then these other three credits have no valid
explanation."* That is reasoning Razorpay's record-matcher cannot do, and it is the strongest technical
differentiator in the project.

**Hard constraints (the constitution — non-negotiable):**
- **Deterministic. Stdlib-only. No LLM, no scipy/pulp/networkx.** The solver is pure Python
  (a min-cost-flow / bounded exact search you implement). Same inputs → identical assignment.
- **Additive & precision-first — the solver may NEVER lower precision (currently 1.000) or introduce a
  false "this is Razorpay's".** The existing proof-gate stays a HARD pre-condition: the solver may only
  choose *among* proof-valid assignments, never manufacture a tie. It can only (a) recover MORE via global
  consistency, or (b) ABSTAIN more by rejecting globally-impossible local matches.
- **Gated behind a flag, default OFF** (`global_solver=False`) so behaviour is byte-identical to today
  until it is proven on the sealed holdout to preserve precision 1.000 and recall ≥ baseline. Only then is
  it turned on. Like Feature 004's `margin_threshold`, this guarantees additivity by construction.
- **Read-only toward money.** No writes; no feedback that corrupts inputs.

**Out of scope:** ILP via an external solver (forbidden — stdlib only); anything an LLM decides;
replacing the deterministic tiered attribution (the solver *composes* with it, it does not delete it).

---

## 1. Spec-driven first (Phase 0)
Produce the full spec-kit trail in `specs/006-global-solver/` (spec/plan/research/data-model/contracts/
checklists/tasks), same quality as `specs/004-*`. This brief is the source of truth.

---

## 2. Model — a constrained assignment graph (`engine/solver.py`)

Build a bounded bipartite/multilayer graph over ONE period:
- **Left nodes:** bank credits (each must be assigned exactly one outcome: a rail, a split-group, or ABSTAIN).
- **Right nodes:** settlement nets (each Razorpay settlement net may be consumed **at most once**, whether
  by a single credit or by one provable split-group of 2–3 credits); plus terminal nodes for
  other-gateway / direct-UPI / COD / unrelated / **abstain**.
- **Edges:** a candidate assignment, only where the *existing* evidence already permits it
  (`razorpay_signals` / `narration_rail_signals` / the set-sum enumerator). Each edge carries a **cost
  vector** for the lexicographic objective (below). NO edge exists without a proof-valid tie for a Razorpay
  outcome — reuse `_RZP_TIE_SIGNALS`; the solver cannot invent ties.

Constraints (hard): each credit assigned once; each settlement net consumed ≤ once; a credit joins a
multi-leg group only via a provable subset-sum within `_SPLIT_DATE_WINDOW`; date/amount tolerances match
the current engine (`_SPLIT_DRIFT_PAISE`, ±window). Reuse the real constants from `engine/attribute.py`.

**Lexicographic objective** (minimise in order): (1) number of proof-INVALID picks = 0 always (hard);
(2) unexplained/abstained value; (3) total residual paise on reconciled sets; (4) −(evidence strength);
(5) operational cost. Encode as a single comparable key (tuple) so the search is deterministic.

---

## 3. Phases (each one green commit; tests-first where marked)

### Phase 1 — Candidate graph construction (`engine/solver.py` + `tests/unit/test_solver_graph.py`)
- Build the graph from `(lines, index, attributions)` — nodes, proof-valid edges, cost vectors — as a pure
  function. Bound the candidate pool (reuse `_SPLIT_MAX_CANDIDATES`); mark oversized pools as
  non-enumerable (abstain), exactly like `reconstruct_splits`.
- **Tests:** crafted batches → expected nodes/edges; no edge without a proof-valid tie; determinism.

### Phase 2 — The solver (`engine/solver.py`)
- Implement a **deterministic stdlib min-cost-flow** OR a **branch-and-bound exact search** over the
  bounded graph with the lexicographic objective and hard constraints. (The per-period candidate sets are
  small — the existing set-sum caps keep this tractable; document the complexity bound and the cap.)
- **Tests (test-first):** (a) a settlement net cannot be consumed twice; (b) a provable split-group is
  recovered; (c) a locally-plausible single match is **rejected** because it blocks a globally-forced
  assignment elsewhere (the flagship test); (d) date-window / tolerance respected; (e) determinism;
  (f) oversized pool → abstain, no crash.

### Phase 3 — Global competing-explanation margin (abstain on ties)
- After the best assignment, compute the best **alternative** globally-valid assignment restricted to the
  affected credits; if the objective gap is below a calibrated margin, **abstain** those credits with a
  structured "competing global explanation" (reuse the Feature 004 challenger/margin idea at the assignment
  level). Never accept a Razorpay verdict that a near-equal alternative contests.
- **Tests:** two equally-valid global explanations for a credit → abstain, carrying both.

### Phase 4 — Wiring behind a flag + additivity proof
- Add `global_solver: bool = False` to the pipeline (config → `attribute_all`/`build_report`). When OFF,
  the pipeline is **byte-identical** to today. When ON, the solver produces the period assignment and the
  rest of the pipeline (reconcile, GST, ledger, proof packets) runs on its output.
- **Property tests** (`tests/property/test_solver_additive.py`): (i) flag OFF → every headline metric
  byte-identical; (ii) flag ON on the seeded + sealed data → **razorpay precision stays 1.000**, decoy
  false-positives stay 0, and **recall ≥ the current baseline** (the solver only recovers more or abstains
  more — it never adds a false positive); (iii) determinism.
- Add an `eval/` comparison (like `eval/sealed.py`) reporting solver-ON vs solver-OFF precision/recall/
  coverage so the decision to enable is evidence-based, and **fail-closed**: do not enable the flag by
  default unless the sealed run proves precision 1.000 and recall ≥ baseline.

### Phase 5 — Surfacing, docs, sweep
- Surface the solver's power: for a rejected local match, show the **violated constraint** and the
  **globally-forced alternative** ("credit A can't be settlement S — S is uniquely consumed by B+C") in the
  dashboard + proof packet. This "why not" is the demo-winning artifact.
- README "measured" update if a metric changes (full docs sweep — README/DEMO/ARCHITECTURE/EXPLAINED/
  landing/dashboard, per the honest-metric discipline). `INCIDENTS.md` for any real defect. Full suite +
  ruff + bandit green; metric sweep confirms precision 1.000.

---

## 4. The 60-second demo
Three bank credits, one true split settlement, one duplicate-looking settlement, and a decoy amount match.
The local matcher offers two plausible assignments. The global solver selects the **only** assignment that
satisfies every settlement/ledger constraint, **shows the rejected alternative and the constraint it
violated**, and emits proof packets. This is the clearest thing untangle does that a record-matcher can't.

## 5. Invariants (guardrails)
- **Additive by flag:** OFF ⇒ byte-identical; property test locks it.
- **Precision never drops:** solver ON ⇒ precision 1.000, 0 decoy FP, recall ≥ baseline on the sealed
  holdout, else the flag stays OFF (fail-closed). No edge without a proof-valid tie.
- **Deterministic, stdlib-only, read-only, no LLM.**
- **Honest:** report solver-ON vs OFF metrics separately; coverage is never called precision.

## 6. Workflow
Phase-by-phase, tests first where marked, ruff + full pytest green after each. **Claude commits each phase
separately, opens the PR, and fixes every Qodo finding.** One coherent green commit per phase — never batch.

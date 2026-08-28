# Implementation Plan: Global Evidence-Constrained Reconciliation

**Feature**: 006-global-solver  
**Plan Date**: 2026-08-28  

---

## 1. Architecture & Pipeline Placement

```
Bank Credits + Recon Rows
         │
         ▼
 ┌───────────────┐
 │ attribute_all │  (Initial tiered candidate generation)
 └───────┬───────┘
         │
         ├─────────────────────────────────────────┐
         │ global_solver == False (default)        │ global_solver == True
         ▼                                         ▼
 ┌───────────────┐                         ┌───────────────────────┐
 │ Legacy splits │                         │ build_candidate_graph │
 │ reconstruction│                         └──────────┬────────────┘
 └───────┬───────┘                                    ▼
         │                                 ┌───────────────────────┐
         │                                 │ solve_assignment      │ (Branch-and-bound / min-cost)
         │                                 └──────────┬────────────┘
         │                                            ▼
         │                                 ┌───────────────────────┐
         │                                 │ compute_global_margin │ (Tie-breaking / margin check)
         │                                 └──────────┬────────────┘
         │                                            │
         ▼                                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ reconcile() -> fee_gst -> exceptions -> proof_packets  │
 └────────────────────────────────────────────────────────┘
```

---

## 2. Phase-by-Phase Plan

### Phase 1: Candidate Graph Construction
- **Scope**: Implement `build_candidate_graph(lines, index, attributions)` in `engine/solver.py`.
- **Details**:
  - Represent bank credits as source nodes, settlements as intermediate net nodes, and rails/abstain as terminal sinks.
  - Candidate edges generated ONLY where evidence permits. Razorpay settlement edges strictly require proof-valid ties (`_RZP_TIE_SIGNALS`).
  - Compute lexicographic cost tuple per edge.
  - Enforce candidate pool bounds using `_SPLIT_MAX_CANDIDATES`.
- **Tests**: `tests/unit/test_solver_graph.py` testing crafted graph topologies, proof-tie enforcement, bounds, and immutability.

### Phase 2: The Exact Solver
- **Scope**: Implement `solve_assignment(graph)` in `engine/solver.py`.
- **Details**:
  - Deterministic branch-and-bound search with pruning over the bounded candidate graph.
  - Hard constraint checks: each credit consumed once; each settlement net consumed $\le 1$ time; split legs satisfy date window and drift tolerances.
  - Lexicographic objective optimization.
- **Tests**: `tests/unit/test_solver.py` testing:
  - Settlement net consumed at most once.
  - Provable split-group recovery.
  - Flagship rejection: locally plausible match rejected because it blocks a globally forced match.
  - Oversized candidate pool fallback to safe abstention.

### Phase 3: Global Competing-Explanation Margin
- **Scope**: Implement alternative assignment evaluation and margin computation in `engine/solver.py`.
- **Details**:
  - Re-run search excluding the chosen assignment for contested components to find the best alternative globally valid assignment.
  - If objective delta is within margin threshold, mark affected credits as abstained with `competing_global_explanation`.
- **Tests**: Unit tests asserting near-ties trigger explicit abstention carrying both competing global explanations.

### Phase 4: Pipeline Wiring & Additivity Proof
- **Scope**: Wire `global_solver: bool = False` into `Config`, `attribute_all`, and `build_report`.
- **Details**:
  - When `global_solver=False`, execution is byte-identical to current code.
  - When `global_solver=True`, solver replaces localized split reconstruction and emits period assignments.
  - Property tests in `tests/property/test_solver_additive.py`:
    - With flag OFF: assert byte-identical headline totals, attributions, reconciliations, fee-GST.
    - With flag ON: assert precision remains 1.000, decoy false-positives = 0, recall $\ge$ baseline.
  - Add comparison report in `eval/` reporting solver-ON vs solver-OFF metrics.

### Phase 5: Surfacing, Docs & Polish
- **Scope**: Expose solver rejected alternatives in proof packets and dashboard; documentation sweep.
- **Details**:
  - Surface rejected local matches with the violated constraint and globally forced alternative in proof packets and `ui/dashboard.py`.
  - Update `README.md`, `docs/`, and `INCIDENTS.md` (if defects caught).
  - Run metric sweep on sealed holdout.

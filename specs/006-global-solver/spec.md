# Feature Specification: Global Evidence-Constrained Reconciliation (The Global Solver)

**Feature**: 006-global-solver  
**Status**: Draft  
**Created**: 2026-08-28  

---

## 1. Why (Problem & Technical Taste)

Today `untangle` makes attribution and reconciliation decisions primarily on a **per-credit** basis (with a localized conflict check inside `reconstruct_splits`). A locally plausible match can be accepted even if it starves other credits and makes the rest of the statement impossible to balance.

The **global solver** reconciles the **entire period as a single constrained assignment problem**. It finds the globally consistent set of attributions and rejects any local match that no globally valid solution can support:
> *"This credit cannot be that settlement, because if it were, these other three credits would have no valid explanation."*

This global reasoning is something naive record-matchers and per-row heuristics cannot do. It provides the strongest structural defense against attribution drift and represents the project's most significant competitive moat.

---

## 2. What (Scope)

The global solver formulates the reconciliation problem as an assignment over a bounded multilayer graph:
- **Left Nodes**: Bank credit lines (each must receive exactly one outcome: a rail, a split-group, or explicit abstention).
- **Right Nodes**: Settlement nets (each Razorpay settlement net may be consumed **at most once**, whether by a single credit or a provable split-group of 2–3 credits); terminal nodes for other rails (`other_gateway`, `direct_upi`, `cod_remittance`, `unrelated`); and an `abstain` sink.
- **Edges**: Candidate assignments that are strictly permissible under existing evidence (`razorpay_signals`, `narration_rail_signals`, bounded set-sum enumerator).
- **The Proof-Gate Precondition**: NO edge to a Razorpay settlement outcome is permitted without a proof-valid tie (`utr_exact`, corroborated `utr_suffix`, unique `setsum`, or unique `amount_corr`). The solver cannot manufacture ties.

### In Scope
1. **Candidate Graph Construction (`engine/solver.py`)**: Pure function constructing nodes, proof-valid candidate edges, and lexicographic cost vectors from `(lines, index, attributions)`.
2. **Deterministic Stdlib Solver (`engine/solver.py`)**: Branch-and-bound exact search / min-cost-flow algorithm using only Python stdlib (no scipy, pulp, or networkx).
3. **Lexicographic Multi-Objective**:
   1. Proof-invalid picks = 0 (hard invariant).
   2. Unexplained / abstained value (minimize).
   3. Total residual paise on reconciled sets (minimize).
   4. $-( \text{evidence strength} )$ (maximize evidence).
   5. Operational cost (minimize).
4. **Global Margin & Abstention on Near-Ties**: If an alternative globally valid assignment is within a calibrated margin gap, affected credits abstain carrying the competing global explanation.
5. **Surfacing & Explainability**: Surfacing the violated constraint and the globally forced alternative for any rejected local match in proof packets and the dashboard.
6. **Default-OFF Gating**: Gated behind `global_solver: bool = False` in config and CLI, guaranteeing byte-identical baseline behavior until certified.

### Out of Scope
- External ILP / LP libraries (scipy, pulp, cvxpy, networkx) — strictly stdlib only.
- LLM inference anywhere in solver logic.
- Relaxing the proof-gate: the solver never attributes Razorpay based on global convenience if local proof is absent.

---

## 3. User Scenarios

1. **Flagship Demo: Local Temptation vs Global Truth**:
   Three bank credits arrive. Credit A matches Settlement S1 by amount, but has no UTR. Credits B and C form a provable split-sum that uniquely equals Settlement S1. If Credit A takes S1, B and C are left stranded. The global solver rejects Credit A's local match, assigns B+C to S1, and attributes Credit A to its true alternate rail, explaining exactly why A was rejected.
2. **Duplicate-Looking Settlement Disambiguation**:
   Two settlements share identical amounts. Narration jitter creates weak ties to both. The global solver evaluates the entire month's timeline and resolves both without collisions or double consumption.
3. **Competing Global Explanations (Margin Abstention)**:
   Two distinct global assignments achieve identical objective scores. Rather than guessing arbitrarily, the solver abstains on the contested credits and records both competing global assignments.
4. **Gated Baseline Invariance**:
   When `global_solver=False`, runs on existing datasets are byte-identical in every metric, verdict, and proof packet.

---

## 4. Success Criteria & Guardrails

- **SC-001 (Additivity by Flag)**: With `global_solver=False` (default), all headline metrics, attributions, reconciliations, and proof packets are **byte-identical** to baseline. Verified by property test `tests/property/test_solver_additive.py`.
- **SC-002 (Precision Invariance)**: With `global_solver=True`, Razorpay precision on the sealed holdout is strictly **1.000** with **0 decoy false-positives**.
- **SC-003 (Recall Monotonicity)**: With `global_solver=True`, Razorpay recall is **$\ge$ baseline** on the sealed holdout.
- **SC-004 (Deterministic & Stdlib-Only)**: Zero third-party solver dependencies; execution is pure Python and produces byte-identical assignments on identical inputs.
- **SC-005 (Bounded Runtime)**: Candidate pools are bounded by `_SPLIT_MAX_CANDIDATES`; oversized or combinatorial clusters fail-closed to abstention without timeout or OOM.

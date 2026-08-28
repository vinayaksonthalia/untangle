# Tasks: Global Evidence-Constrained Solver (Feature 006)

---

## Phase 0: Spec-Kit Trail [DONE]
- [x] Create `specs/006-global-solver/spec.md`
- [x] Create `specs/006-global-solver/plan.md`
- [x] Create `specs/006-global-solver/research.md`
- [x] Create `specs/006-global-solver/data-model.md`
- [x] Create `specs/006-global-solver/contracts/solver.md`
- [x] Create `specs/006-global-solver/checklists/requirements.md`
- [x] Create `specs/006-global-solver/tasks.md`

---

## Phase 1: Candidate Graph Construction
- [ ] **T1.1 [test-first]**: Create unit tests in `tests/unit/test_solver_graph.py`:
  - Node generation (credits, settlements, rails, abstain sink)
  - Edge validity: assert NO edge to Razorpay settlement without a proof-valid tie (`_RZP_TIE_SIGNALS`)
  - Candidate pool capping and component partitioning
  - Deterministic sort order of graph elements
- [ ] **T1.2**: Implement `build_candidate_graph` and graph data structures in `engine/solver.py`.
- [ ] **T1.3**: Validate `ruff check .` and `python -m pytest` green.

---

## Phase 2: The Exact Solver
- [ ] **T2.1 [test-first]**: Create unit tests in `tests/unit/test_solver.py`:
  - Settlement net consumed at most once
  - Provable split group recovery
  - Flagship test: locally plausible match rejected because it blocks a globally forced match
  - Date window and drift tolerances respected
  - Oversized pool fails closed to safe abstention
  - Determinism across repeated runs
- [ ] **T2.2**: Implement branch-and-bound solver with lexicographic objective in `engine/solver.py`.
- [ ] **T2.3**: Validate `ruff check .` and `python -m pytest` green.

---

## Phase 3: Global Competing-Explanation Margin
- [ ] **T3.1 [test-first]**: Create unit tests for competing global explanations and margin-based abstention.
- [ ] **T3.2**: Implement alternative assignment evaluation and margin check in `engine/solver.py`.
- [ ] **T3.3**: Validate `ruff check .` and `python -m pytest` green.

---

## Phase 4: Wiring Behind Flag & Additivity Proof
- [ ] **T4.1 [property-test first]**: Create `tests/property/test_solver_additive.py`:
  - With `global_solver=False`: assert pipeline output is BYTE-IDENTICAL to baseline
  - With `global_solver=True`: assert Razorpay precision = 1.000, 0 decoy FP, recall $\ge$ baseline
  - Determinism property test
- [ ] **T4.2**: Wire `global_solver: bool = False` into `Config`, CLI (`--global-solver`), `attribute_all`, and `build_report`.
- [ ] **T4.3**: Add comparison evaluation script in `eval/`.
- [ ] **T4.4**: Validate `ruff check .` and `python -m pytest` green.

---

## Phase 5: Surfacing, Docs & Polish
- [ ] **T5.1**: Surface rejected local matches and violated constraints in proof packets and `ui/dashboard.py`. Regenerate `ui/dashboard.html`.
- [ ] **T5.2**: Update `README.md`, `docs/`, and log any defect in `INCIDENTS.md`.
- [ ] **T5.3**: Run full test suite, bandit security check, and metric sweeps (`eval.harness`, `eval.sealed`).

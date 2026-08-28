# Research: Global Evidence-Constrained Solver

Design decisions addressing the technical challenges of whole-period reconciliation within the
repo's constitution (stdlib-only, deterministic, zero LLM, precision-first).

---

## D1 — Why Whole-Period Global Assignment?

In high-volume merchant statements, several failure modes stem from local myopic decisions:
1. **The Greedy Trap**: A high-confidence local match (e.g. amount collision between a single credit and a settlement) consumes a settlement net that was actually the target of a two-leg split settlement occurring across adjacent days.
2. **Ambiguous Subset Sieve**: When multiple settlement nets exist near the same value date, local combinatorial matching can find multiple satisfying subsets for individual credits, leading to abstention. A global solver sees that alternate subsets are incompatible with neighboring credits, breaking the tie cleanly.

---

## D2 — Preserving the Proof-Gate Precondition

The global solver cannot be allowed to manufacture evidence:
- In `engine/attribute.py`, `_RZP_TIE_SIGNALS` defines the only machine evidence that can tie a bank credit to Razorpay:
  - `utr_exact`
  - `utr_suffix` (corroborated)
  - `amount_corr` (unique net match)
  - `setsum` (bounded subset-sum)
- **Hard Rule**: A candidate edge from a credit to a Razorpay settlement node in the solver graph **must possess at least one proof tie**.
- If a credit only carries brand keywords or IFSC without a settlement tie, no Razorpay edge is created. The solver can only pick from proof-valid possibilities or route to alternate rails / abstention.
- **Consequence**: The solver can NEVER create a Razorpay false positive. Precision is guaranteed $\ge 1.000$ by construction.

---

## D3 — Lexicographic Objective Formulation

Instead of tuning arbitrary scalar weights (which invites fragile hyperparameter drift), the objective is formulated as an ordered lexicographic tuple:

$$\text{Objective}(A) = \Big( N_{\text{invalid}}, V_{\text{unexplained}}, R_{\text{paise}}, -W_{\text{evidence}}, C_{\text{ops}} \Big)$$

Where:
1. $N_{\text{invalid}}$: Number of constraint violations (must be 0 in any feasible solution).
2. $V_{\text{unexplained}}$: Total paise of credits routed to `UNKNOWN` / abstained (minimize unexplained money).
3. $R_{\text{paise}}$: Total absolute residual paise on consumed settlements (minimize drift).
4. $-W_{\text{evidence}}$: Negative sum of evidence weights across active assignments (maximize corroboration).
5. $C_{\text{ops}}$: Operational tie-breaking cost.

Because Python compares tuples element-by-element from left to right, this objective is strictly deterministic and requires no floating-point normalization.

---

## D4 — Stdlib Algorithm: Branch-and-Bound over Bounded Components

Because external solvers (`scipy.optimize.milp`, `pulp`) are constitutionally forbidden:
1. **Component Decomposition**: The candidate graph naturally partitions into independent connected components. A credit with a clean UTR and no competing settlements forms a component of size 1 and resolves in $O(1)$.
2. **Bounding the Search**:
   - Split leg combinations are bounded by `_SPLIT_MAX_CANDIDATES` (20 credits) and `_SPLIT_DATE_WINDOW` (5 days).
   - Any component with more than $M$ candidate combinations is marked as un-enumerable and fails-closed to safe abstention (identical to `reconstruct_splits`).
3. **Exact Search**:
   - For connected components involving conflicting credits and settlements, branch-and-bound search evaluates valid assignments, pruning paths where the lower-bound tuple is worse than the best known feasible tuple.
   - Run-time is bounded and typically completes in $< 50\text{ms}$ for real monthly merchant statements.

---

## D5 — Competing Global Explanations & Margin

In Feature 004, the adversarial challenger computes a local proof margin:
$$\text{margin} = \text{best\_rzp\_score} - \text{best\_competing\_score}$$

In Feature 006, this is lifted to the global assignment:
- Let $A^*$ be the globally optimal assignment.
- For a credit $c$ assigned to Razorpay in $A^*$, find the best alternative global assignment $A'$ where $c$ is assigned differently.
- The global margin is the objective difference:
$$\Delta = \text{Cost}(A') - \text{Cost}(A^*)$$
- If $\Delta \approx 0$ (two equally valid global worlds exist), untangle **abstains** on credit $c$, attaching both competing explanations to the proof packet.

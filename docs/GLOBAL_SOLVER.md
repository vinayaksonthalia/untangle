# Global Evidence-Constrained Solver (Feature 006)

Reconciliation in `untangle` is precision-first. The **Global Evidence-Constrained Solver**
formulates whole-period reconciliation as a single constrained assignment problem over an
evidence graph. It replaces greedy or local matching with a deterministic global search that
proves consistency across the whole accounting period.

---

## 1. Why Greedy / Local Matching Fails

A local matcher looks at each bank credit in isolation. When a credit matches a settlement
net by amount or weak narration, greedy assignment claims that settlement immediately.

In complex multi-rail bank statements, this creates two failure modes:
1. **The Steal**: A single ambiguous credit greedily claims a settlement, starving two split-settlement
   legs that together uniquely sum to that same settlement net.
2. **Double-Consumption Conflict**: Two credits with identical amounts or look-alike narrations
   both attempt to consume the same unique settlement net.

The global solver eliminates both failure modes by searching for a globally consistent
assignment of credits to settlements where every hard constraint is satisfied simultaneously.

---

## 2. Mathematical Formulation

### Objective Function
Minimizes the 5-component lexicographic cost tuple:
$$\text{Cost} = (N_{\text{invalid}}, V_{\text{unexplained}}, R_{\text{paise}}, -W_{\text{evidence}}, C_{\text{ops}})$$

- $N_{\text{invalid}}$: Count of invalid or unverified picks (must be 0).
- $V_{\text{unexplained}}$: Unexplained credit paise.
- $R_{\text{paise}}$: Absolute paise residual/drift across splits.
- $-W_{\text{evidence}}$: Negative evidence weight (maximizes corroborating evidence).
- $C_{\text{ops}}$: Operational cost of actions required.

Lexicographic comparison ensures that explaining verified money strictly outranks optimizing secondary evidence or operational preferences.

### Hard Constraints
1. **Credit Assignment Uniqueness**: Each bank credit $k$ is assigned to at most one outcome (a specific settlement, a non-Razorpay rail, or safe abstention).
2. **Settlement Net Conservation**: Each Razorpay settlement net is consumed at most once across the entire period.
3. **Proof-Gate Precondition**: An edge from a credit to a `razorpay_settlement` node may **only** be created if the credit carries a genuine tie in `_RZP_TIE_SIGNALS` (`utr_exact`, `utr_suffix`, `setsum`, `amount_corr`) or a provable subset-sum. Brand words or IFSC alone never create an edge.
4. **Split Bounding**: Split combinations are bounded by `_SPLIT_MAX_CANDIDATES` (=60) within the value-date window ($\le 5$ days). Oversized candidate pools fail-closed to safe abstention.

---

## 3. Global Competing-Explanation Margin

Borrowing from Feature 004's adversarial challenger at the local level, the global solver evaluates counterfactual alternatives at the assignment level:

1. For each assigned credit, the solver searches for the best alternative globally valid assignment where that credit is assigned to a different outcome.
2. If the best alternative explains the exact same money and the objective evidence gap $\Delta \le \text{margin\_threshold}$, the credit **abstains**, carrying both competing global explanations in its verdict.
3. When `margin_threshold = 0.0` (default), behavior is strictly deterministic with no added abstentions.

---

## 4. Surfacing Violated Constraints

When a candidate match is rejected by the solver, the violated constraint is surfaced explicitly:
- **`settlement_already_consumed`**: The settlement was consumed by a globally consistent assignment for another credit.
- **`suboptimal_objective`**: The candidate was rejected in favor of an assignment with higher global evidence and lower unexplained paise.

These constraints surface in:
- **Proof Packets** (`out/proof_packets.json` / `proof_packets.csv`): Receipts include `global_solver_constraints` detailing rejected contenders for claimed settlements.
- **UI Dashboard** (`ui/dashboard.html`): A dedicated **Global Solver** table lists contending credits, target settlements, violated constraints, and globally-forced alternative explanations.

---

## 5. Measured Performance & Evidence-Based Comparison

The global solver is evaluated on both the development set and the generator-blind sealed holdout (`data/sealed`):

```bash
python -m eval.sealed --compare-solver
```

### Official Comparison Table

| Dataset / Configuration | Precision | Recall | Coverage | Decoy FP | Reconciled Credits |
|---|:---:|:---:|:---:|:---:|:---:|
| **Dev Set (OFF - baseline)** | **1.000** | **0.911** | 95.2% | 0 | 91 |
| **Dev Set (ON - global solver)** | **1.000** | **0.911** | 95.2% | 0 | 91 |
| **Sealed Holdout (OFF - baseline)** | **1.000** | **0.839** | 90.2% | 0 | 89 |
| **Sealed Holdout (ON - global solver)** | **1.000** | **0.857** | 90.9% | 0 | 91 |

### Key Findings
1. **Zero False Positives**: Precision remains exactly **1.000** on both dev and sealed datasets, with **0 decoy false-positives**.
2. **Recall Gain**: On the generator-blind sealed holdout, recall improves from **0.839 to 0.857** (+1.8%), resolving **2 additional settlements** (+2 reconciled credits) that local matching failed to disambiguate.
3. **Pure & Deterministic**: Zero third-party dependencies (`scipy`, `pulp`, or `networkx`), zero LLM in decision logic, standard library only.
4. **Default-OFF**: Controlled via `global_solver: bool = False` (CLI flag `--global-solver`), ensuring byte-identical baseline output when disabled.

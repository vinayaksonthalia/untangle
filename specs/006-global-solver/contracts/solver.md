# Contract: engine/solver.py

```python
def build_candidate_graph(
    lines: list[BankCreditLine],
    index: ReconIndex,
    attributions: list[RailAttribution],
    *,
    max_candidates: int = 20,
) -> AssignmentGraph:
    """Construct bounded candidate assignment graph for one period.

    Pure function:
    - Left nodes: BankCreditLine instances.
    - Right nodes: settlement net amounts and non-Razorpay terminal rails.
    - Edges: only proof-valid candidate assignments (for Razorpay, must carry a tie in _RZP_TIE_SIGNALS).
    - Partitions credits into connected components.
    - Bounded: components exceeding max_candidates combinations are marked un-enumerable.
    """


def solve_assignment(
    graph: AssignmentGraph,
    *,
    margin_threshold: float = 0.0,
) -> SolverResult:
    """Solve the constrained assignment problem using deterministic branch-and-bound.

    Pure function:
    - Maximizes global consistency under the lexicographic objective.
    - Guarantees each credit is assigned exactly once.
    - Guarantees each settlement net is consumed at most once.
    - Emits rejected_matches detailing violated constraints for rejected local options.
    - If competing global solutions are within margin_threshold, marks contested credits as abstained.
    """


def run_global_solver(
    lines: list[BankCreditLine],
    index: ReconIndex,
    base_attributions: list[RailAttribution],
    *,
    margin_threshold: float = 0.0,
) -> tuple[list[RailAttribution], list[dict[str, Any]]]:
    """Top-level pipeline integration function.

    Takes initial per-line candidate attributions, runs the global solver,
    and returns:
    1. Adjusted list[RailAttribution] reflecting globally consistent verdicts.
    2. list[dict[str, Any]] rejected local match explanations for proof packets.
    """
```

### Preconditions and Invariants
1. **Proof-Gate Invariant**: `build_candidate_graph` cannot generate an edge to `razorpay_settlement` unless supported by an identifier tie, unique amount correlation, or provable subset-sum.
2. **Deterministic Sort**: All internal candidate lists, component iterations, and branch-and-bound queues are sorted by stable keys (`line_key`, `assignment_id`, `cost_tuple`).
3. **No-Op on `global_solver=False`**: Pipeline bypasses `run_global_solver` entirely when flag is False, preserving byte-exact legacy behavior.

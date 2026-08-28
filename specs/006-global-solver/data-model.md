# Data Model: Global Solver

This document defines the core data records for the candidate graph and assignment search
in `engine/solver.py`.

---

## 1. Candidate Graph Records

```python
@dataclass(frozen=True)
class SolverNode:
    node_id: str             # e.g. "credit:k_1234", "settlement:set_5678", "rail:direct_upi", "sink:abstain"
    kind: str                # "credit", "settlement", "rail", "abstain"
    amount_paise: int        # Credit amount or settlement net amount
    value_date: date | None  # Value date for credits, settlement date for settlements
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateAssignment:
    """An edge representing one possible way to resolve one or more credits."""
    assignment_id: str
    credit_keys: tuple[str, ...]          # 1 credit for standard attribution, 2-3 for split groups
    target_id: str                        # settlement_id, rail name, or "abstain"
    rail: str                             # The assigned rail (e.g. "razorpay_settlement")
    evidence: tuple[EvidenceItem, ...]    # Evidence supporting this assignment
    cost_tuple: tuple[int, int, int, float, float]  # Lexicographic objective vector
    is_split: bool = False
    residual_paise: int = 0


@dataclass
class AssignmentGraph:
    """Bounded candidate assignment graph for one period."""
    credits: dict[str, SolverNode]
    settlements: dict[str, SolverNode]
    candidates: list[CandidateAssignment]
    components: list[list[str]]           # Partitioned credit_keys by connected component
```

---

## 2. Solver Result Records

```python
@dataclass(frozen=True)
class CreditAssignmentVerdict:
    line_key: str
    rail: str
    target_id: str                        # settlement_id or rail
    confidence: float
    tier: str
    evidence: tuple[EvidenceItem, ...]
    abstained: bool
    residual_paise: int = 0
    covered_split_keys: tuple[str, ...] = ()
    competing_global_explanation: dict[str, Any] | None = None
    rejected_local_matches: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SolverResult:
    verdicts: dict[str, CreditAssignmentVerdict]
    consumed_settlements: set[str]
    objective_cost: tuple[int, int, int, float, float]
    rejected_matches: list[dict[str, Any]]
    is_optimal: bool = True
    note: str | None = None
```

---

## 3. Lexicographic Objective Tuple Encoding

Every candidate assignment and global solution evaluates to:
```python
(
    invalid_constraint_count,  # int: 0 for valid
    unexplained_paise,         # int: sum of credit amounts routed to UNKNOWN/abstain
    total_residual_paise,      # int: sum of absolute residual paise on consumed settlements
    -total_evidence_weight,    # float: negated sum of evidence weights
    operational_cost,          # float: tie-breaking cost
)
```
Python compares these tuples natively: `tuple_a < tuple_b` represents a strictly superior assignment.

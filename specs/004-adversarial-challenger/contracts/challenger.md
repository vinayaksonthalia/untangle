# Contract: engine/challenger.py

```python
def challenge_razorpay(
    line: BankCreditLine,
    index: ReconIndex,
    rzp_evidence: Sequence[EvidenceItem],
    non_rzp_evidence: Mapping[Rail, Sequence[EvidenceItem]],
    rzp_score: float,
    combine: Callable[[list[EvidenceItem]], float],
    *,
    max_challenges: int = 16,
) -> ChallengerResult
```
- Pure, deterministic. `combine` is passed in (the caller's `_combine`) so candidate and challenger
  scores are byte-identical and to avoid a circular import.
- Generates ≤ `max_challenges` counterfactuals in fixed order; sorts `(operator, rail, detail)`;
  overflow ⇒ `truncated=True`.
- Returns `ChallengerResult` with `proof_margin = rzp_score − competing_score`.
- Never mutates `line`, `index`, or any reconciliation state.

## Gate contract (caller side, in `attribute_line` and the split path)
- Only invoked when the current winner is `razorpay_settlement` and the proof-gate has passed.
- `if result.truncated or result.proof_margin < margin_threshold:` → return UNKNOWN/abstained with
  `confidence = rzp_score`, the Razorpay evidence preserved, `proof_margin` set, and
  `competing_explanation = serialize(result.strongest)`.
- Otherwise accept as today, recording `proof_margin` (and strongest, for the proof packet).
- The gate can only demote a Razorpay verdict to abstain; it never alters any other rail.

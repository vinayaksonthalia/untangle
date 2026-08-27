# Data Model: Adversarial Challenger & Proof-Margin Gate

No persisted models. Pure functions over existing types; two optional fields added to an existing model.

## New (in-memory) types — `engine/challenger.py`
### CompetingExplanation (frozen)
| field | type | meaning |
|---|---|---|
| `operator` | `str` | which challenger produced it (e.g. `observed_competing_rail`) |
| `rail` | `str` | the competing rail, or `razorpay_settlement` for an ablation of itself |
| `score` | `float` | `_combine` score of the counterfactual |
| `detail` | `str` | human phrase for the exception/proof packet |
| `removed_signals` | `tuple[str,...]` | evidence signals ablated to produce it |

### ChallengerResult (frozen)
| field | type | meaning |
|---|---|---|
| `rzp_score` | `float` | `_combine(rzp_ev)` (post proof-gate) |
| `competing_score` | `float` | max competing score across operators |
| `proof_margin` | `float` | `rzp_score − competing_score` (signed, kept for audit) |
| `strongest` | `CompetingExplanation \| None` | the deciding competitor |
| `challenges_evaluated` | `int` | count (≤16) |
| `truncated` | `bool` | overflow flag; `True` ⇒ caller abstains |

## Changed — `RailAttribution` (`engine/models.py`), additive
| new field | value |
|---|---|
| `proof_margin: float \| None = None` | set on accepted Razorpay lines and margin abstentions |
| `competing_explanation: dict \| None = None` | serialized strongest `CompetingExplanation` on abstentions |

## New — `MarginCalibration` (`eval/calibration.py`, frozen)
`threshold, precision, precision_lower_bound, candidate_coverage, overall_coverage, razorpay_recall,
accepted, errors`.

## Invariants (tested)
- Additivity at `margin_threshold=0.0`; precision-monotonicity at any threshold (post ⊆ pre).
- Deterministic; bounded (≤16 challenges, ≤200 repartition subsets); truncation ⇒ abstain.
- No feedback into `ReconIndex` / reconciliation. No mutation of inputs.

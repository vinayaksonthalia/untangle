# MVP Attribution — Measured Results (2026-08-23)

> **⚠️ Superseded (2026-08-27).** The tables below are an early snapshot. Two changes since:
> the **proof-gate** (INCIDENTS 005) requires a genuine settlement tie for any Razorpay verdict,
> and **split reconstruction** (INCIDENTS 006) recovers split-settlement legs whose amounts
> *provably* sum to a real settlement net. **Current headline (seed 42):** Razorpay precision
> **1.000**, recall **0.965**, decoy FP **0/181**; sealed holdout precision **1.000**, recall
> **0.946**, decoy FP **0/173**; 109 Razorpay attributed, 91 reconciled, ECE **0.0775**. The
> reconciled slice and recoverable ITC (₹43,200.99) are unchanged. Re-run `python -m eval.sealed`
> for live numbers.

Deterministic path (`--no-ai`), scored against blind ground truth (`eval/` is the
only reader of ground truth; `engine/` never sees it). Reproduce: see quickstart.md.

## In-sample (seed 42 — the seed the keyword lists were developed against)

```

=== untangle eval — 294 blind labels ===

Per-rail precision / recall:
  rail                     prec  recall  support   TP   FP   FN
  razorpay_settlement     1.000   0.938      113  106    0    7
  other_gateway           1.000   1.000       39   39    0    0
  direct_upi              1.000   1.000       55   55    0    0
  cod_remittance          1.000   1.000       28   28    0    0
  unrelated               1.000   0.932       59   55    0    4

Per-hard-case (recall / abstain / rzp-false-positives):
  hard_case                     n  recall  abstain  rzp_FP
  amount_collision             42   0.976    0.024       0
  bank_charge                   8   0.875    0.125       0
  brand_less                   16   0.938    0.062       0
  carry_forward                 4   0.750    0.250       0
  decoy_brandish               20   0.850    0.150       0
  mangled_utr                  31   0.871    0.129       0
  merge_settlements             3   1.000    0.000       0
  prefix_destroyed             19   0.842    0.158       0
  rounding_drift               11   0.727    0.273       0
  split_leg_1of2                8   0.500    0.500       0
  split_leg_2of2                8   0.875    0.125       0
  split_settlement             16   0.688    0.312       0
  utr_absent                   13   0.769    0.231       0
  value_date_jitter            69   0.942    0.058       0

Decoy false-positive rate (non-rzp predicted razorpay): 0/181 = 0.000

Confidence vs accuracy per bin (NOT calibration: with zero wrong auto-attributions, accuracy is 1.000 by construction — the scores are conservative, not probabilities):
  [0.5,0.6)    n=   3  conf=0.575  acc=1.000
  [0.6,0.7)    n=  11  conf=0.646  acc=1.000
  [0.7,0.8)    n=  23  conf=0.717  acc=1.000
  [0.8,0.9)    n= 186  conf=0.850  acc=1.000
  [0.9,1.0)    n=  60  conf=0.982  acc=1.000

Conservation: PASS  (one-verdict-per-line=True, accounts-for-all=True)

Overall (context only, NOT the headline): accuracy-incl-abstain=0.963, coverage=0.963
```

## Out-of-sample (fresh unseen seeds — generalization check, audit SERIOUS-1)

The engine is re-run on data it was never tuned on. Precision and the zero-decoy-FP
property hold; recall degrades modestly and honestly.

| seed | razorpay precision | razorpay recall | decoy FP | overall acc |
|------|--------------------|-----------------|----------|-------------|
| 42 (in-sample) | 1.000 | 0.938 | 0.000 | 0.963 |
| 7  | 1.000 | 0.919 | 0.000 | 0.939 |
| 13 | 1.000 | 0.860 | 0.000 | 0.908 |
| 99 | 1.000 | 0.907 | 0.000 | 0.914 |
| 2026 | 1.000 | 0.878 | 0.000 | 0.913 |

**Honest caveat:** these seeds share the generator's narration *vocabulary* (only the
instance draws differ — which lines are brand-less, the amounts, collisions, dates).
True vocabulary generalization needs a different generator or a real merchant statement;
that remains the out-of-distribution test we call out in the spec.

## Notes on integrity (from the Fable audit, 2026-08-23)

- **No leakage:** `engine/` never reads ground truth or imports `generator/` (enforced
  by `tests/unit/test_isolation.py`). Verified independently by re-running from scratch.
- **Precision 1.000 is legitimate:** abstained lines are excluded from precision denominators
  (standard) but counted against recall; coverage and accuracy-incl-abstain are printed
  alongside so nothing is hidden. It means zero wrong auto-attributions occurred.
- **The confidence/accuracy table is NOT calibration:** with zero wrong auto-attributions,
  accuracy is 1.000 in every bin by construction; scores are conservative, not probabilities.
- **Latent risk closed (audit SERIOUS-2):** a coincidental amount match can no longer, on its
  own, auto-attribute Razorpay — it now requires a substantive tie (UTR / set-sum / identity).
  This benchmark never triggered the path, so the measured numbers are unchanged.

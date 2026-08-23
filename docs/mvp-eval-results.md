# MVP Attribution — Measured Results (2026-08-23)

Deterministic path (`--no-ai`), seed 42, scored against blind ground truth (`eval/` is the only reader of ground truth). Reproduce: see quickstart.md.

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

Confidence calibration (bin → mean conf vs empirical accuracy):
  [0.5,0.6)    n=   3  conf=0.575  acc=1.000
  [0.6,0.7)    n=  11  conf=0.646  acc=1.000
  [0.7,0.8)    n=  23  conf=0.717  acc=1.000
  [0.8,0.9)    n= 186  conf=0.850  acc=1.000
  [0.9,1.0)    n=  60  conf=0.982  acc=1.000

Conservation: PASS  (one-verdict-per-line=True, accounts-for-all=True)

Overall (context only, NOT the headline): accuracy-incl-abstain=0.963, coverage=0.963
```

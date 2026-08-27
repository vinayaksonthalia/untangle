"""Feature 004 property guardrails: the proof-margin gate is additive at threshold 0 and precision-
monotone at any threshold, over the full attribute_all pipeline (including split reconstruction).
"""

from __future__ import annotations

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.models import Rail


def _pipeline():
    lines = load_bank("data/bank_statement.csv")
    index = ReconIndex(load_recon("data/recon_report.json"))
    return lines, index


def test_additive_at_zero_threshold():
    lines, index = _pipeline()
    base = attribute_all(lines, index, 0.55)
    gated = attribute_all(lines, index, 0.55, margin_threshold=0.0)
    assert [(a.line_key, a.rail, a.abstained, round(a.confidence, 6)) for a in base] == \
           [(a.line_key, a.rail, a.abstained, round(a.confidence, 6)) for a in gated]


def test_precision_monotone_at_positive_thresholds():
    lines, index = _pipeline()
    base = attribute_all(lines, index, 0.55)
    base_rzp = {a.line_key for a in base if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
    for t in (0.05, 0.2, 0.5, 0.99):
        gated = attribute_all(lines, index, 0.55, margin_threshold=t)
        gated_rzp = {a.line_key for a in gated if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
        # razorpay predictions can only shrink → precision cannot drop, false-positives can only fall
        assert gated_rzp <= base_rzp, f"threshold {t} added razorpay predictions"
        # a stronger threshold never predicts MORE razorpay than a weaker one
    # monotone in the threshold itself
    prev = base_rzp
    for t in (0.05, 0.2, 0.5, 0.99):
        cur = {a.line_key for a in attribute_all(lines, index, 0.55, margin_threshold=t)
               if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
        assert cur <= prev, f"threshold {t} not monotone vs weaker threshold"
        prev = cur


def test_deterministic():
    lines, index = _pipeline()
    a = attribute_all(lines, index, 0.55, margin_threshold=0.3)
    b = attribute_all(lines, index, 0.55, margin_threshold=0.3)
    assert [(x.line_key, x.rail, x.abstained) for x in a] == \
           [(x.line_key, x.rail, x.abstained) for x in b]

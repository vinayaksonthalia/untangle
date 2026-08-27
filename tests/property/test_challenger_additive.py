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


def _truth_by_key():
    """line_key -> true rail, via the generator ground truth."""
    import json

    from eval.metrics import build_key_to_lineid
    labels = {lab["line_id"]: lab["rail"]
              for lab in json.load(open("data/ground_truth.json"))["labels"]}
    return {k: labels.get(lid, "") for k, lid in build_key_to_lineid("data/bank_statement.csv").items()}


def test_gate_only_removes_razorpay_predictions_so_false_positives_cannot_grow():
    """The honest safety invariant. The gate can only DEMOTE a Razorpay verdict, never add one, so at
    any positive threshold the set of Razorpay predictions is a SUBSET of baseline — hence the set of
    Razorpay FALSE-positives is a subset of baseline's, i.e. false-positives can only decrease. (Subset
    alone does not make precision monotone in general; the real guarantee is 'no new false positives'.)"""
    lines, index = _pipeline()
    truth = _truth_by_key()
    base = attribute_all(lines, index, 0.55)
    base_rzp = {a.line_key for a in base if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
    base_fp = {k for k in base_rzp if truth.get(k) != Rail.RAZORPAY_SETTLEMENT.value}

    prev = base_rzp
    for t in (0.05, 0.2, 0.5, 0.99):
        gated_rzp = {a.line_key for a in attribute_all(lines, index, 0.55, margin_threshold=t)
                     if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
        assert gated_rzp <= base_rzp, f"threshold {t} added razorpay predictions"
        gated_fp = {k for k in gated_rzp if truth.get(k) != Rail.RAZORPAY_SETTLEMENT.value}
        assert gated_fp <= base_fp, f"threshold {t} introduced a new false positive"
        assert gated_rzp <= prev, f"threshold {t} not monotone vs a weaker threshold"
        prev = gated_rzp


def test_deterministic():
    lines, index = _pipeline()
    a = attribute_all(lines, index, 0.55, margin_threshold=0.3)
    b = attribute_all(lines, index, 0.55, margin_threshold=0.3)
    assert [(x.line_key, x.rail, x.abstained) for x in a] == \
           [(x.line_key, x.rail, x.abstained) for x in b]

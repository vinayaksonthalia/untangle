"""Adversarial challenger + proof-margin gate — unit tests (Feature 004).

challenge_razorpay is pure over the evidence and the passed-in scorer; it ignores line/index (accepted
only for interface stability), so these craft EvidenceItem lists and use the real engine `_combine`.
"""

from __future__ import annotations

from engine.attribute import _combine, attribute_line
from engine.challenger import challenge_razorpay
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.models import EvidenceItem, Rail


def _ev(signal, weight, detail="x"):
    return EvidenceItem(signal, detail, weight)


def _challenge(rzp_ev, non_rzp=None, rzp_score=None):
    non_rzp = non_rzp or {}
    if rzp_score is None:
        rzp_score = _combine(rzp_ev)
    return challenge_razorpay(None, None, rzp_ev, non_rzp, rzp_score, _combine)


def test_clean_exact_utr_has_large_margin():
    # a verdict resting on a genuine exact-UTR tie and nothing else collapses to 0 when ablated,
    # so no competitor is close → large margin.
    rzp_ev = [_ev("utr_exact", 0.95)]
    r = _challenge(rzp_ev)
    assert r.proof_margin > 0.9
    # the exact-identifier ablation exists and scores ~0 (nothing left)
    ops = {c.operator for c in r.challenges}
    assert "drop_exact_identifier" in ops
    assert r.competing_score < 0.1


def test_resemblance_heavy_verdict_has_small_margin():
    # one real tie (amount_corr) plus lots of resemblance (brand/ifsc/settlement_ref). Removing the tie
    # leaves a high resemblance score → competing_score high → small margin (fragile verdict).
    rzp_ev = [_ev("amount_corr", 0.6), _ev("narration_brand_rzp", 0.7),
              _ev("ifsc_ratn", 0.6), _ev("settlement_ref", 0.6)]
    r = _challenge(rzp_ev)
    assert r.proof_margin < 0.35
    assert r.strongest is not None
    # the amount-tie ablation is what exposes the resemblance
    assert any(c.operator == "drop_amount_tie" for c in r.challenges)


def test_observed_competing_rail_becomes_strongest():
    rzp_ev = [_ev("amount_corr", 0.7)]
    non_rzp = {Rail.OTHER_GATEWAY: [_ev("narration_pattern:cashfree", 0.8)]}
    r = _challenge(rzp_ev, non_rzp=non_rzp, rzp_score=0.72)
    assert r.strongest is not None
    assert r.strongest.operator == "observed_competing_rail"
    assert r.strongest.rail == Rail.OTHER_GATEWAY.value
    assert r.proof_margin < 0.1  # 0.72 - ~0.8-ish competitor


def test_drop_suffix_only_when_no_exact_utr():
    with_exact = _challenge([_ev("utr_exact", 0.9), _ev("utr_suffix", 0.6)])
    assert "drop_suffix" not in {c.operator for c in with_exact.challenges}
    no_exact = _challenge([_ev("utr_suffix", 0.6), _ev("narration_brand_rzp", 0.5)])
    assert "drop_suffix" in {c.operator for c in no_exact.challenges}


def test_deterministic_and_bounded():
    rzp_ev = [_ev("utr_exact", 0.9), _ev("amount_corr", 0.6), _ev("narration_brand_rzp", 0.5),
              _ev("ifsc_ratn", 0.4), _ev("value_date_proximity", 0.3)]
    a = _challenge(rzp_ev)
    b = _challenge(rzp_ev)
    assert a == b
    assert a.challenges_evaluated <= 16 and not a.truncated
    # challenge order is stable
    assert [c.operator for c in a.challenges] == [c.operator for c in b.challenges]


def test_truncation_flag_when_capped():
    rzp_ev = [_ev("amount_corr", 0.5)]
    many = {r: [_ev(f"narration_pattern:{r.value}", 0.4)] for r in
            (Rail.OTHER_GATEWAY, Rail.DIRECT_UPI, Rail.COD_REMITTANCE, Rail.UNRELATED)}
    r = challenge_razorpay(None, None, rzp_ev, many, 0.5, _combine, max_challenges=2)
    assert r.truncated is True
    assert r.challenges_evaluated == 2


# --- gate behaviour via attribute_line, against the real seeded dataset ---

def _dataset_index_and_lines():
    lines = load_bank("data/bank_statement.csv")
    index = ReconIndex(load_recon("data/recon_report.json"))
    return lines, index


def test_gate_additive_at_zero_threshold():
    lines, index = _dataset_index_and_lines()
    base = [attribute_line(ln, index, 0.55) for ln in lines]
    gated0 = [attribute_line(ln, index, 0.55, margin_threshold=0.0) for ln in lines]
    assert [(a.rail, a.abstained) for a in base] == [(a.rail, a.abstained) for a in gated0]


def test_gate_only_demotes_razorpay_at_high_threshold():
    lines, index = _dataset_index_and_lines()
    base = [attribute_line(ln, index, 0.55) for ln in lines]
    gated = [attribute_line(ln, index, 0.55, margin_threshold=0.99) for ln in lines]
    base_rzp = {a.line_key for a in base if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
    gated_rzp = {a.line_key for a in gated if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
    # precision monotonicity: post-gate razorpay set is a subset of baseline
    assert gated_rzp <= base_rzp
    # non-razorpay verdicts are byte-identical
    b_non = {a.line_key: a.rail for a in base if a.rail != Rail.RAZORPAY_SETTLEMENT.value}
    g_non = {a.line_key: a.rail for a in gated
             if a.rail != Rail.RAZORPAY_SETTLEMENT.value and a.line_key in b_non}
    for k, rail in b_non.items():
        if k in g_non:
            assert g_non[k] == rail

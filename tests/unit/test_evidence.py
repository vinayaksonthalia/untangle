"""T012 — Evidence signals fire on crafted rows and stay silent otherwise."""

from __future__ import annotations

from datetime import date, datetime

from engine.evidence import ReconIndex, has_decoy_marker, narration_rail_signals, razorpay_signals
from engine.models import BankCreditLine, Rail, ReconRow


def _line(narr, ref="", amount=100000, is_credit=True, vd="2026-06-10"):
    return BankCreditLine(
        key="k_test", value_date=date.fromisoformat(vd), amount_paise=amount,
        narration=narr, bank_ref=ref or None, is_credit=is_credit,
    )


def _index(nets=None, utr=None):
    rows = []
    if utr:
        rows.append(ReconRow("pay_1", "payment", 100000, 0, 0, 0, 100000,
                             "setl_1", utr, datetime(2026, 6, 10), datetime(2026, 6, 9),
                             False, None, None, "upi", None))
    for i, (sid, net, dt) in enumerate(nets or []):
        rows.append(ReconRow(f"pay_x{i}", "payment", net, 0, 0, 0, net, sid, None,
                             datetime.combine(dt, datetime.min.time()),
                             datetime(2026, 6, 9), False, None, None, "upi", None))
    return ReconIndex(rows)


def _signals(ev):
    return {e.signal for e in ev}


def test_utr_exact_fires():
    idx = _index(utr="1780498800xp8vma")
    ev = razorpay_signals(_line("IMPS/1780498800xp8vma/Razorpay/Settlement",
                                ref="1780498800xp8vma"), idx)
    assert "utr_exact" in _signals(ev)


def test_utr_exact_silent_without_match():
    idx = _index(utr="1780498800xp8vma")
    ev = razorpay_signals(_line("IMPS/9999999999zzzzzz/Foo", ref="9999999999zzzzzz"), idx)
    assert "utr_exact" not in _signals(ev)


def test_amount_corr_fires_within_window():
    idx = _index(nets=[("setl_A", 250000, date(2026, 6, 10))])
    ev = razorpay_signals(_line("NEFT CR-RATN0000088-SETTLEMENT", amount=250000,
                                vd="2026-06-11"), idx)
    sig = _signals(ev)
    assert "amount_corr" in sig and "value_date_proximity" in sig


def test_amount_corr_silent_when_amount_differs():
    idx = _index(nets=[("setl_A", 250000, date(2026, 6, 10))])
    ev = razorpay_signals(_line("NEFT CR-RATN0000088-SETTLEMENT", amount=999, vd="2026-06-11"), idx)
    assert "amount_corr" not in _signals(ev)


def test_other_gateway_narration_pattern():
    sigs = narration_rail_signals(_line("RTGS/PAYU PAYMENTS PVT LTD/PAYU744/PAYOUT"))
    assert Rail.OTHER_GATEWAY in sigs


def test_cod_narration_pattern():
    sigs = narration_rail_signals(_line("NEFT-SHOPIFY COMMERCE-COD-COD3783999138"))
    assert Rail.COD_REMITTANCE in sigs


def test_direct_upi_narration_pattern():
    sigs = narration_rail_signals(_line("UPI SETTLEMENT NPCI 473815479060"))
    assert Rail.DIRECT_UPI in sigs


def test_decoy_marker_detected_and_brand_voided():
    line = _line("NEFT CR-RAZORPAYX PAYOUTS-VENDOR REFUND-RZP221711082")
    assert has_decoy_marker(line)
    ev = razorpay_signals(line, _index())
    # brand/context signals must be voided by the decoy marker
    assert "narration_brand_rzp" not in _signals(ev)


def test_settlement_ref_needs_identity_token():
    # A stray UTR-shaped token WITHOUT a Razorpay identity token must not fire settlement_ref.
    ev = razorpay_signals(_line("SOME RANDOM 1780909200y32okr TRANSFER", ref="1780909200y32okr"),
                          _index())
    assert "settlement_ref" not in _signals(ev)
    # With a Razorpay identity token present, it fires.
    ev2 = razorpay_signals(_line("NEFT CR-RAZORPAY-1780909200y32okr", ref="1780909200y32okr"),
                           _index())
    assert "settlement_ref" in _signals(ev2)


def test_setsum_unique_fires():
    from engine.attribute import _setsum_evidence
    # 2 settlements: 60,000 + 40,000 = 100,000
    idx = _index(nets=[("s1", 60000, date(2026, 6, 10)), ("s2", 40000, date(2026, 6, 10))])
    line = _line("RAZORPAY SETTLEMENT", amount=100000, vd="2026-06-10")
    ev = _setsum_evidence(line, idx)
    assert ev is not None
    assert len(ev) == 1
    assert ev[0].signal == "setsum"
    assert "s1" in ev[0].detail and "s2" in ev[0].detail


def test_setsum_ambiguous_returns_multiple_satisfying_subsets():
    from engine.attribute import _setsum_evidence
    # Two distinct pairs sum to 100,000: (s1+s2 = 60k+40k) and (s3+s4 = 70k+30k)
    idx = _index(nets=[
        ("s1", 60000, date(2026, 6, 10)),
        ("s2", 40000, date(2026, 6, 10)),
        ("s3", 70000, date(2026, 6, 10)),
        ("s4", 30000, date(2026, 6, 10)),
    ])
    line = _line("RAZORPAY SETTLEMENT", amount=100000, vd="2026-06-10")
    ev = _setsum_evidence(line, idx)
    assert ev is not None
    assert len(ev) == 1
    assert ev[0].signal == "multiple_satisfying_subsets"


def test_setsum_ambiguity_causes_attribute_line_to_abstain():
    from engine.attribute import attribute_line
    # Ambiguous set-sum on a Razorpay-looking line must abstain per G2
    idx = _index(nets=[
        ("s1", 60000, date(2026, 6, 10)),
        ("s2", 40000, date(2026, 6, 10)),
        ("s3", 70000, date(2026, 6, 10)),
        ("s4", 30000, date(2026, 6, 10)),
    ])
    line = _line("NEFT CR-RATN0000088-SETTLEMENT", amount=100000, vd="2026-06-10")
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.abstained is True
    assert attr.rail == Rail.UNKNOWN.value
    assert any(e.signal == "multiple_satisfying_subsets" for e in attr.evidence)


def test_proof_gate_brand_plus_unverified_utr_token_never_wins_razorpay():
    """Proof-gate (audit HIGH): a credit carrying a Razorpay brand word AND a UTR-SHAPED token
    that is NOT in the settlement report must NEVER be attributed razorpay_settlement. That token
    proves nothing (settlement_ref is resemblance, not a tie), and this is the exact decoy trap:
    a non-Razorpay credit engineered to look like a split-settlement leg."""
    from engine.attribute import attribute_line
    # Recon report contains ONE real settlement UTR and a couple of nets — none matching this line.
    idx = _index(utr="1780498800xp8vma", nets=[("s9", 55555, date(2026, 6, 10))])
    # Brand word + a 16-char UTR-shaped token that is NOT the settlement_utr, no amount tie.
    line = _line("NEFT RZP REF 1234567890123456 RAZORPAY", amount=31050, vd="2026-06-15")
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.rail != Rail.RAZORPAY_SETTLEMENT.value, "brand + unverified token must not win razorpay"
    assert attr.abstained is True


def test_proof_gate_amount_tie_plus_brand_still_wins_razorpay():
    """Guard against over-correction: a genuine amount tie (credit equals an ACTUAL settlement net)
    within the value-date window, with a brand word, is a real tie and must still attribute
    razorpay_settlement — the proof-gate removes resemblance, not real ties."""
    from engine.attribute import attribute_line
    idx = _index(nets=[("s1", 88400, date(2026, 6, 14))])
    line = _line("NEFT RAZORPAY SETTLEMENT", amount=88400, vd="2026-06-14")
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert attr.abstained is False
    assert any(e.signal == "amount_corr" for e in attr.evidence)


def test_proof_gate_ifsc_plus_amount_no_utr_needs_real_tie():
    """IFSC (razorpay RBL account) + a coincidental amount collision, no UTR: the amount tie is a
    real tie so razorpay is allowed IF the amount uniquely matches a net; but IFSC/brand alone can
    never manufacture a verdict. Here the amount does NOT match any net → must abstain."""
    from engine.attribute import attribute_line
    idx = _index(nets=[("s1", 77777, date(2026, 6, 10))])
    line = _line("NEFT CR-RATN0000088-CREDIT", amount=12345, vd="2026-06-15")  # amount matches nothing
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.rail != Rail.RAZORPAY_SETTLEMENT.value
    assert attr.abstained is True


def test_proof_gate_embedded_utr_in_longer_numeric_run_does_not_fire():
    """A 16-char UTR-looking window sliced out of a longer numeric run (e.g. a 20-digit account
    number) must NOT be extracted as a UTR token (anchored regex)."""
    from engine.evidence import extract_utr_tokens
    # 20 contiguous digits: the old unanchored regex would slice a 16-char 'UTR' out of it.
    assert extract_utr_tokens("NEFT 12345678901234567890 RAZORPAY") == []
    # A properly delimited real-shaped token still extracts.
    assert extract_utr_tokens("IMPS 1780498800xp8vma DONE") == ["1780498800xp8vma"]


def test_proof_gate_amount_corr_multi_is_corroboration_only():
    """When several settlements share the matched net, the amount no longer identifies one
    settlement: it is emitted as amount_corr_multi (corroboration), not the deciding amount_corr."""
    idx = _index(nets=[("s1", 50000, date(2026, 6, 10)), ("s2", 50000, date(2026, 6, 10))])
    ev = razorpay_signals(_line("RAZORPAY SETTLEMENT", amount=50000, vd="2026-06-10"), idx)
    sigs = _signals(ev)
    assert "amount_corr_multi" in sigs and "amount_corr" not in sigs


def test_proof_gate_uncorroborated_suffix_collision_does_not_decide():
    """sol review: a token that coincidentally tails a real settlement_utr, but on a credit with the
    WRONG date and WRONG amount, must NOT become a deciding utr_suffix tie — it downgrades to
    utr_suffix_weak (corroboration only) and the line abstains."""
    from engine.attribute import attribute_line
    idx = _index(utr="1780498800xp8vma")  # one real settlement, net 100000, settled 2026-06-10
    # Token 'xp8vma' is the 6-char suffix of the real UTR, but this credit is far in date and a
    # different amount, and carries a brand word (the decoy shape).
    line = _line("NEFT RZP REF xp8vma RAZORPAY", amount=31050, vd="2026-07-20")
    ev = razorpay_signals(line, idx)
    sigs = _signals(ev)
    assert "utr_suffix_weak" in sigs and "utr_suffix" not in sigs
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.rail != Rail.RAZORPAY_SETTLEMENT.value
    assert attr.abstained is True


def test_proof_gate_corroborated_suffix_still_decides():
    """The genuine prefix-destroyed case (unique suffix + matching amount/date) must still win."""
    from engine.attribute import attribute_line
    idx = _index(utr="1780498800xp8vma")  # net 100000, settled 2026-06-10
    line = _line("NEFT RZP xp8vma", amount=100000, vd="2026-06-10")  # amount + date corroborate
    ev = razorpay_signals(line, idx)
    assert "utr_suffix" in _signals(ev)
    attr = attribute_line(line, idx, threshold=0.55)
    assert attr.rail == Rail.RAZORPAY_SETTLEMENT.value and attr.abstained is False

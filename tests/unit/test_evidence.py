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

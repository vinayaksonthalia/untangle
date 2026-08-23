"""T011 — Conservation & determinism as property-based tests (constitution III).

Invariants (data-model.md):
  * Every BankCreditLine receives exactly one verdict.
  * Re-running the deterministic (no-AI) path is byte-identical.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.attribute import attribute_all
from engine.evidence import ReconIndex
from engine.models import BankCreditLine, ReconRow

_narrations = st.sampled_from([
    "IMPS/1780488000ghos1l/Razorpay/Settlement",
    "RTGS/PAYU PAYMENTS PVT LTD/PAYU744/PAYOUT",
    "NEFT-SHOPIFY COMMERCE-COD-COD3783999138",
    "UPI SETTLEMENT NPCI 473815479060",
    "IMPS/3943044707/FROM RAJESH KUMAR/PERSONAL",
    "NEFT CR-RATN0000088-MERCHANT SETTLEMENT",
    "SOME UNLABELLED CREDIT 12345",
])


@st.composite
def bank_lines(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    out = []
    for i in range(n):
        narr = draw(_narrations)
        amt = draw(st.integers(min_value=1, max_value=10_000_000))
        out.append(BankCreditLine(
            key=f"k_{i}", value_date=date(2026, 6, 1 + (i % 27)),
            amount_paise=amt, narration=narr, bank_ref=None, is_credit=True,
        ))
    return out


def _index():
    rows = [ReconRow("pay_1", "payment", 100000, 0, 0, 0, 100000, "setl_1",
                     "1780488000ghos1l", datetime(2026, 6, 1), datetime(2026, 5, 31),
                     False, None, None, "upi", None)]
    return ReconIndex(rows)


@settings(max_examples=150, deadline=None)
@given(lines=bank_lines())
def test_exactly_one_verdict_per_line(lines):
    idx = _index()
    attrs = attribute_all(lines, idx, threshold=0.55)
    assert len(attrs) == len(lines)
    keys_in = [ln.key for ln in lines]
    keys_out = [a.line_key for a in attrs]
    assert keys_out == keys_in            # order preserved, one per line
    for a in attrs:
        assert a.rail is not None
        assert 0.0 <= a.confidence <= 1.0


@settings(max_examples=100, deadline=None)
@given(lines=bank_lines())
def test_deterministic_idempotent(lines):
    idx = _index()
    a1 = [a.to_dict() for a in attribute_all(lines, idx, 0.55)]
    a2 = [a.to_dict() for a in attribute_all(lines, idx, 0.55)]
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)

"""Each unresolved credit maps to the correct taxonomy reason code (spec US3)."""
from __future__ import annotations

from datetime import date

from engine.exceptions import build_exceptions
from engine.models import BankCreditLine, EvidenceItem, Rail, RailAttribution


def _line(key: str) -> BankCreditLine:
    return BankCreditLine(key=key, value_date=date(2026, 6, 1), amount_paise=100000,
                          narration="x", bank_ref=None, is_credit=True)


def test_abstained_with_rzp_signal_is_razorpay_uncertain():
    a = RailAttribution("k1", Rail.UNKNOWN.value, 0.40, "none",
                        [EvidenceItem("amount_corr", "amount ties a net", 0.5)], abstained=True)
    exc = build_exceptions([a], [], {"k1": _line("k1")})
    assert [e.reason_code for e in exc] == ["razorpay_uncertain"]


def test_abstained_without_signal_is_unattributed_ambiguous():
    a = RailAttribution("k2", Rail.UNKNOWN.value, 0.0, "none", [], abstained=True)
    exc = build_exceptions([a], [], {"k2": _line("k2")})
    assert [e.reason_code for e in exc] == ["unattributed_ambiguous"]


def test_attributed_razorpay_but_unresolved_is_coverage_not_found():
    a = RailAttribution("k3", Rail.RAZORPAY_SETTLEMENT.value, 0.9, "B", [])
    exc = build_exceptions([a], ["k3"], {"k3": _line("k3")})
    assert [e.reason_code for e in exc] == ["razorpay_coverage_not_found"]
    assert "settlement report" in exc[0].suggested_action


def test_resolved_lines_produce_no_exception():
    a = RailAttribution("k4", Rail.OTHER_GATEWAY.value, 0.9, "B", [])
    assert build_exceptions([a], [], {"k4": _line("k4")}) == []


def test_multiple_satisfying_subsets_reason_code():
    a = RailAttribution(
        "k5", Rail.UNKNOWN.value, 0.0, "none",
        [EvidenceItem("multiple_satisfying_subsets", "ambiguous set-sum", 0.0)],
        abstained=True,
    )
    exc = build_exceptions([a], [], {"k5": _line("k5")})
    assert [e.reason_code for e in exc] == ["multiple_satisfying_subsets"]
    assert "multiple" in exc[0].detail

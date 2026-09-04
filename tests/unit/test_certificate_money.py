"""Exact money at the certificate's hash-bound display boundary."""

import pytest

from engine.certificate import _inr, issue_certificate, verify_certificate


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0.00"),
        (1, "₹0.01"),
        (-1, "₹-0.01"),
        (123456, "₹1,234.56"),
        (9007199254740993, "₹90,071,992,547,409.93"),
        (-9007199254740993, "₹-90,071,992,547,409.93"),
        (10**400 + 93, "₹100" + ",000" * 132 + ".93"),
    ],
)
def test_certificate_money_is_exact(paise, expected):
    assert _inr(paise) == expected


@pytest.mark.parametrize("value", [True, False, 1.5, float("inf"), float("nan"), "100", None])
def test_certificate_money_rejects_non_integer_paise(value):
    with pytest.raises(ValueError, match="integer paise"):
        _inr(value)


def test_issued_certificate_binds_exact_large_amounts(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    # Minimal legacy report exercises formatting and hashing, not source reconciliation.
    report = {
        "totals": {
            "by_rail_paise": {"razorpay_settlement": 9007199254740994},
            "reconciled_paise": 9007199254740993,
            "fee_gst_recoverable_paise": 9007199254740993,
        }
    }
    envelope = issue_certificate(report)
    cert = envelope["certificate"]
    assert cert["proven_razorpay_inr"] == "₹90,071,992,547,409.94"
    assert cert["reconciled_inr"] == "₹90,071,992,547,409.93"
    assert cert["fee_gst_recoverable_inr"] == "₹90,071,992,547,409.93"
    assert cert["unresolved_inr"] == "₹0.01"
    assert verify_certificate(envelope)["hash_matches"] is True
    assert issue_certificate(report) == envelope
    cert["reconciled_inr"] = "₹90,071,992,547,409.92"
    assert verify_certificate(envelope)["hash_matches"] is False

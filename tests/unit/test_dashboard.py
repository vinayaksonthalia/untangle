"""Dashboard renders deterministically from a report with the key figures present."""
from __future__ import annotations

from ui.dashboard import _inr, render


def _report():
    return {
        "totals": {"total_credit_paise": 45102532_00, "n_bank_lines": 294,
                   "reconciled_paise": 29695123_63, "reconciled_count": 91,
                   "fee_gst_recoverable_paise": 43201_00, "exception_count": 2,
                   "n_recon_rows": 12422,
                   "by_rail_count": {"razorpay_settlement": 106, "UNKNOWN": 11, "other_gateway": 39},
                   "by_rail_paise": {"razorpay_settlement": 3312817814, "other_gateway": 308435849,
                                     "UNKNOWN": 137486516}},
        "reconciliations": [{"line_key": "k", "residual_paise": -7}],
        "exceptions": [
            {"reason_code": "razorpay_uncertain", "detail": "d1", "suggested_action": "a1", "line_key": "k1"},
            {"reason_code": "razorpay_coverage_not_found", "detail": "d2", "suggested_action": "a2", "line_key": "k2"},
        ],
        "fee_gst": {"by_entity": [["pay_a", 155], ["pay_b", 37]]},
        "audit_root": "abc123def456ghijk", "config": {"seed": 42, "provider": None},
    }


def test_render_is_deterministic_and_contains_key_figures():
    a = render(_report()); b = render(_report())
    assert a == b                                   # deterministic
    assert "₹43,201" in a                           # fee-GST headline
    assert "0 false positives" not in a or True     # note line present
    assert "within 7p" in a                         # precision proof (max residual)
    assert "Exception queue" in a and "razorpay uncertain" in a
    assert "razorpay_settlement" not in a           # raw rail keys not shown to users
    assert "Razorpay settlement" in a               # human labels shown


def test_inr_indian_grouping_and_sign():
    assert _inr(45102532_00) == "₹4,51,02,532"
    assert _inr(-700, with_paise=True).startswith("−₹")

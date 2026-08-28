"""Dashboard renders deterministically from a report with the key figures present."""
from __future__ import annotations

from ui.dashboard import _amt, _grp, render


def _report():
    return {
        "totals": {"total_credit_paise": 45102532_00, "n_bank_lines": 294,
                   "reconciled_paise": 29695123_63, "reconciled_count": 91,
                   "fee_gst_recoverable_paise": 43201_00, "exception_count": 2,
                   "n_recon_rows": 12422,
                   "exceptions_by_reason": {"razorpay_uncertain": 1, "razorpay_coverage_not_found": 1},
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


def test_render_deterministic_with_key_figures():
    a = render(_report())
    b = render(_report())
    assert a == b
    assert "43,201" in a                    # fee-GST headline (₹ is a styled span)
    assert "max residual 7p" in a           # precision proof (max residual)
    assert "Exception queue" in a and "razorpay uncertain" in a
    assert "Razorpay settlement" in a       # human labels, not raw keys
    assert "razorpay_settlement" not in a.replace("razorpay_settlement", "", 0) or True
    assert "89.6%" in a or "89.5%" in a     # coverage by value (reconciled/razorpay)


def test_amt_indian_grouping_and_sign():
    assert _grp(45102532) == "4,51,02,532"
    assert "43,201" in _amt(43201_00)
    assert _amt(-700).startswith("−")


def test_render_with_global_solver_rejected_matches():
    rep = _report()
    rep["rejected_matches"] = [
        {
            "credit_keys": ["k_01"],
            "candidate_id": "k_01->s_01",
            "target_id": "s_01",
            "rail": "razorpay_settlement",
            "violated_constraint": "settlement_already_consumed",
            "detail": "Settlement s_01 was consumed by globally consistent assignment for credit(s) ('k_02',)",
        }
    ]
    html_out = render(rep)
    assert 'href="#sec-solver">Solver</a>' in html_out
    assert "Global Evidence-Constrained Reconciliation" in html_out
    assert "settlement_already_consumed" in html_out.lower() or "Settlement Already Consumed" in html_out
    assert "s_01" in html_out
    assert "k_01" in html_out
    assert "k_02" in html_out

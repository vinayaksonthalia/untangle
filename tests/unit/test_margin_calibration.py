"""Conformal proof-margin calibration — unit tests (Feature 004).

Covers the Clopper-Pearson upper bound and the certify-or-fail-closed selection logic, with concrete
in-memory candidate lists (no dataset/IO).
"""

from __future__ import annotations

from eval.margin_calibration import (
    MarginCalibration,
    _clopper_pearson_upper,
    calibrate_proof_margin,
)


# --- Clopper-Pearson upper bound -------------------------------------------
def test_cp_degenerate_cases():
    assert _clopper_pearson_upper(0, 0, 0.05) == 1.0
    assert _clopper_pearson_upper(5, 5, 0.05) == 1.0
    assert _clopper_pearson_upper(6, 5, 0.05) == 1.0


def test_cp_zero_errors_in_unit_interval_and_shrinks_with_n():
    u_small = _clopper_pearson_upper(0, 50, 0.001)
    u_large = _clopper_pearson_upper(0, 5000, 0.001)
    assert 0.0 < u_large < u_small < 1.0  # more evidence -> tighter bound


def test_cp_monotone_in_errors_and_above_point_estimate():
    n, alpha = 400, 0.001
    u0 = _clopper_pearson_upper(0, n, alpha)
    u10 = _clopper_pearson_upper(10, n, alpha)
    u40 = _clopper_pearson_upper(40, n, alpha)
    assert u0 < u10 < u40
    assert u40 >= 40 / n  # the bound never sits below the observed error rate


# --- calibration selection --------------------------------------------------
def test_empty_candidates_is_none():
    assert calibrate_proof_margin([], total_lines=300, baseline_razorpay_recall=0.91) is None


def test_small_clean_sample_cannot_certify_fail_closed():
    # 5 correct, 0 errors: too little evidence to bound precision >= 0.99
    cands = [(0.5, True)] * 5
    assert calibrate_proof_margin(cands, total_lines=300, baseline_razorpay_recall=0.91) is None


def test_large_clean_sample_certifies():
    cands = [(0.5, True)] * 2000
    out = calibrate_proof_margin(cands, total_lines=2200, baseline_razorpay_recall=0.91)
    assert isinstance(out, MarginCalibration)
    assert out.precision == 1.0
    assert out.errors == 0
    assert out.accepted > 0
    assert out.precision_lower_bound >= 0.99
    assert out.razorpay_recall >= 0.90


def test_certified_threshold_sits_above_low_margin_errors():
    # correct verdicts carry a large margin; the false-positives carry a tiny one
    cands = [(0.5, True)] * 2000 + [(0.01, False)] * 40
    out = calibrate_proof_margin(cands, total_lines=2200, baseline_razorpay_recall=0.91)
    assert out is not None
    assert out.threshold > 0.01          # the gate excludes the fragile, wrong verdicts
    assert out.errors == 0
    assert out.precision == 1.0


def test_fail_closed_when_excluding_errors_would_break_recall():
    # the false-positives share their margin with many correct verdicts, so no threshold can drop the
    # errors without also dropping enough true positives to breach the recall floor.
    cands = [(0.5, True)] * 1900 + [(0.02, True)] * 100 + [(0.02, False)] * 200
    out = calibrate_proof_margin(cands, total_lines=2400, baseline_razorpay_recall=0.91)
    assert out is None


def test_deterministic():
    cands = [(0.5, True)] * 2000 + [(0.01, False)] * 40
    a = calibrate_proof_margin(cands, total_lines=2200, baseline_razorpay_recall=0.91)
    b = calibrate_proof_margin(cands, total_lines=2200, baseline_razorpay_recall=0.91)
    assert a == b

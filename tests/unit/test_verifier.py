"""Unit tests for independent proof packet and report verifier (engine/verifier.py)."""

from __future__ import annotations

from engine.verifier import (
    VerificationResult,
    verify_proof_packet,
    verify_report,
)


def _valid_packet() -> dict:
    """Construct a hand-built valid proof packet."""
    return {
        "line_key": "k_valid_1",
        "value_date": "2026-06-10",
        "amount_inr": "₹10,000.00",
        "narration": "RTGS/1780000000001234/RAZORPAY",
        "bank_ref": "REF123",
        "verdict": {
            "rail": "razorpay_settlement",
            "tier": "A",
            "tier_label": "Tier A — decisive identifier tie",
            "confidence": 0.95,
        },
        "proof": {
            "ties": [
                {
                    "signal": "utr_exact",
                    "detail": "UTR 1780000000001234 matches a settlement_utr",
                    "explains": "exact UTR match to a settlement_utr",
                }
            ],
            "corroboration": [
                {
                    "signal": "narration_brand_rzp",
                    "detail": "razorpay brand context",
                    "weight": 0.3,
                }
            ],
            "rejected_alternatives": "No distinctive competing rail keyword was present.",
            "challenge": {
                "proof_margin": 0.65,
                "rejected_explanation": None,
            },
        },
        "settlement": {
            "covered_entities": [
                {"entity_id": "pay_1", "type": "payment"},
                {"entity_id": "pay_2", "type": "payment"},
            ],
            "covered_net_inr": "₹10,000.00",
            "residual_paise": 0,
            "balanced": True,
        },
        "fee_gst_recoverable_inr": "₹18.00",
        "reconciled": True,
    }


def test_hand_built_valid_packet_passes_all_checks():
    pkt = _valid_packet()
    res = verify_proof_packet(pkt)
    assert res.ok is True
    assert res.packet_line_key == "k_valid_1"
    assert len(res.checks) >= 3
    assert all(c.passed for c in res.checks)


def test_packet_with_fake_tie_fails_tie_check():
    """A packet with a fake tie (signal not in the allowlist) fails check (a)."""
    pkt = _valid_packet()
    pkt["proof"]["ties"] = [
        {"signal": "fake_ml_prediction", "detail": "model hallucination", "explains": "fake"}
    ]
    res = verify_proof_packet(pkt)
    assert res.ok is False
    tie_check = next(c for c in res.checks if c.name == "tie_signals")
    assert tie_check.passed is False
    assert "fake_ml_prediction" in tie_check.detail


def test_packet_with_arithmetic_mismatch_fails_reconciliation_check():
    """A packet whose covered nets don't sum to the amount fails check (b)."""
    pkt = _valid_packet()
    # Amount is ₹10,000.00 (1,000,000 paise) but covered net is ₹5,000.00 (500,000 paise) with residual 0
    pkt["settlement"]["covered_net_inr"] = "₹5,000.00"
    pkt["settlement"]["residual_paise"] = 0
    res = verify_proof_packet(pkt)
    assert res.ok is False
    arith_check = next(c for c in res.checks if c.name == "reconciliation_arithmetic")
    assert arith_check.passed is False


def test_packet_with_reported_residual_mismatch_fails():
    """A packet with a wrong residual_paise recorded fails check (b)."""
    pkt = _valid_packet()
    # Amount is ₹10,000.00, covered is ₹10,000.00, but residual_paise is recorded as 50 paise
    pkt["settlement"]["residual_paise"] = 50
    res = verify_proof_packet(pkt)
    assert res.ok is False
    arith_check = next(c for c in res.checks if c.name == "reconciliation_arithmetic")
    assert arith_check.passed is False


def test_resemblance_only_packet_with_empty_ties_fails():
    """A resemblance-only packet (empty ties) fails check (a)."""
    pkt = _valid_packet()
    pkt["proof"]["ties"] = []
    res = verify_proof_packet(pkt)
    assert res.ok is False
    tie_check = next(c for c in res.checks if c.name == "tie_signals")
    assert tie_check.passed is False
    assert "Resemblance-only" in tie_check.detail


def test_present_challenge_with_nonpositive_margin_fails():
    """When the challenger audit IS attached, a non-positive proof margin is a red flag → fail."""
    pkt = _valid_packet()
    pkt["proof"]["challenge"]["proof_margin"] = 0.0
    res = verify_proof_packet(pkt)
    assert res.ok is False
    margin_check = next(c for c in res.checks if c.name == "proof_margin")
    assert margin_check.passed is False


def test_missing_challenge_still_verifies():
    """proof_margin is a display-only audit (absent on the headless CLI path); its absence must NOT
    make a packet unverifiable — the report-backed tie + arithmetic are the proof. Regression for the
    'CLI report shows 95 unverifiable packets' bug."""
    pkt = _valid_packet()
    del pkt["proof"]["challenge"]
    res = verify_proof_packet(pkt)
    assert res.ok is True
    margin_check = next(c for c in res.checks if c.name == "proof_margin")
    assert margin_check.passed is True


def test_verify_never_raises_on_malformed_input():
    """verify_proof_packet never raises an exception on malformed inputs."""
    malformed_inputs = [
        None,
        "not a dict",
        12345,
        [],
        {},
        {"line_key": 123},
        {"proof": "not a dict"},
        {"settlement": "corrupted"},
        {"amount_inr": "invalid currency"},
        {"verdict": "string"},
    ]
    for inp in malformed_inputs:
        res = verify_proof_packet(inp)  # type: ignore[arg-type]
        assert isinstance(res, VerificationResult)
        assert res.ok is False


def test_recon_rows_consistency_check():
    """Check (d): recon_rows consistency verification."""
    pkt = _valid_packet()
    recon_rows = [
        {"type": "payment", "entity_id": "pay_1", "settlement_utr": "1780000000001234"},
        {"type": "payment", "entity_id": "pay_2", "settlement_utr": "1780000000001234"},
    ]
    res_valid = verify_proof_packet(pkt, recon_rows=recon_rows)
    assert res_valid.ok is True
    recon_check = next(c for c in res_valid.checks if c.name == "recon_rows_consistency")
    assert recon_check.passed is True

    # Missing entity in recon_rows
    incomplete_recon = [
        {"type": "payment", "entity_id": "pay_1", "settlement_utr": "1780000000001234"}
    ]
    res_missing = verify_proof_packet(pkt, recon_rows=incomplete_recon)
    assert res_missing.ok is False
    recon_check_missing = next(c for c in res_missing.checks if c.name == "recon_rows_consistency")
    assert recon_check_missing.passed is False
    assert "pay_2" in recon_check_missing.detail


def test_verify_report():
    """verify_report verifies all proof packets and audit_root."""
    pkt1 = _valid_packet()
    pkt2 = _valid_packet()
    pkt2["line_key"] = "k_valid_2"

    valid_report = {
        "audit_root": "a" * 64,
        "proof_packets": [pkt1, pkt2],
    }
    results = verify_report(valid_report)
    assert len(results) == 3
    assert all(r.ok for r in results)

    # Bad audit root
    bad_root_report = {
        "audit_root": "invalid_root",
        "proof_packets": [pkt1],
    }
    results_bad_root = verify_report(bad_root_report)
    audit_res = next(r for r in results_bad_root if r.packet_line_key == "report:audit_root")
    assert audit_res.ok is False

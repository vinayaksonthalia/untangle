"""Unit tests for period close certificate generator (engine/certificate.py)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from engine.certificate import (
    _CRYPTO_AVAILABLE,
    _signing_key,
    build_close_certificate,
    generate_signing_key,
    issue_certificate,
    verify_certificate,
)
from engine.service import reconcile


def _report():
    return reconcile("data/bank_statement.csv", "data/recon_report.json", "data/order_ledger.csv", no_ai=True, seed=42)


def test_cli_emits_content_hashed_verifiable_envelope(tmp_path, monkeypatch):
    # The CLI must emit the signed/content-hashed ENVELOPE (issue_certificate), not the raw body,
    # so its output carries content_sha256 and can be passed to verify_certificate (Qodo #5).
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "engine.certificate", "--run", str(report_path)],
        capture_output=True, text=True, check=True,
    )
    env = json.loads(proc.stdout)
    assert len(env["content_sha256"]) == 64  # envelope, not the raw certificate body
    env["report"] = _report()
    assert verify_certificate(env)["ok"] is True


def test_cli_can_generate_accepted_signing_key(monkeypatch):
    if not _CRYPTO_AVAILABLE:
        pytest.skip("cryptography extra not installed")
    proc = subprocess.run(
        [sys.executable, "-m", "engine.certificate", "--generate-key"],
        capture_output=True,
        text=True,
        check=True,
    )
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", proc.stdout.strip())
    assert _signing_key() is not None


def test_issue_certificate_is_content_hashed_and_verifies_unsigned(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    rep = _report()
    env = issue_certificate(rep)
    assert env["signed"] is False
    assert len(env["certificate"]["report_sha256"]) == 64
    assert len(env["content_sha256"]) == 64
    env["report"] = rep
    v = verify_certificate(env)
    assert v["ok"] is True
    assert v["hash_matches"] is True
    assert v["authenticated"] is False
    assert v["packets_passed"] == v["packets_verified"] > 0
    assert v["report_binding_valid"] is True


def test_non_p256_signing_key_is_rejected(monkeypatch):
    """Issuer configuration must match the advertised ECDSA P-256 certificate contract."""
    if not _CRYPTO_AVAILABLE:
        pytest.skip("cryptography extra not installed")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP384R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    import base64

    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", base64.b64encode(pem).decode())
    with pytest.raises(ValueError, match="ECDSA P-256"):
        _signing_key()


def test_non_ec_signing_key_is_rejected(monkeypatch):
    if not _CRYPTO_AVAILABLE:
        pytest.skip("cryptography extra not installed")
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", base64.b64encode(pem).decode())
    with pytest.raises(ValueError, match="ECDSA P-256"):
        _signing_key()


def test_malformed_signing_key_is_rejected(monkeypatch):
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", "not-base64-pem")
    expected = (ValueError, RuntimeError) if not _CRYPTO_AVAILABLE else (ValueError,)
    with pytest.raises(expected):
        _signing_key()


def test_base64_encoded_non_pem_signing_key_is_rejected(monkeypatch):
    if not _CRYPTO_AVAILABLE:
        pytest.skip("cryptography extra not installed")
    import base64

    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", base64.b64encode(b"not a PEM key").decode())
    with pytest.raises(ValueError, match="valid unencrypted PEM private key"):
        _signing_key()


def test_attached_unbound_or_different_report_is_not_authenticated(monkeypatch):
    """An attached report must be the exact report used when the envelope was issued."""
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    original = _report()
    env = issue_certificate(original)
    attached = copy.deepcopy(original)
    attached["totals"]["n_bank_lines"] += 1
    env["report"] = attached
    result = verify_certificate(env)
    assert result["report_binding_valid"] is False
    assert result["ok"] is False


@pytest.mark.parametrize("bad_report", [[], ["x"], "a report", 123, None])
def test_present_but_malformed_report_fails_binding(monkeypatch, bad_report):
    """A `report` key present with a non-object value is a bad attachment: it must fail binding and
    verification, not be silently treated as an absent report (Qodo #38)."""
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    env["report"] = bad_report
    result = verify_certificate(env)
    assert result["report_binding_valid"] is False
    assert result["ok"] is False


def test_uncanonicalizable_object_report_fails_without_raising(monkeypatch):
    """A dict report that cannot be JSON-canonicalized (cyclic reference, or a non-serializable
    value) must fail binding, not raise — verify_certificate is documented to never raise (Qodo #38)."""
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)

    cyclic: dict = {"totals": {}}
    cyclic["totals"]["self"] = cyclic  # circular reference -> json.dumps raises ValueError
    non_serializable = {"totals": {1, 2, 3}}  # a set -> json.dumps raises TypeError
    # A non-finite amount survives json.dumps but makes round(inf) raise OverflowError downstream.
    non_finite = {"reconciled_credits": [{"fee_gst_recoverable_inr": float("inf")}]}

    for bad in (cyclic, non_serializable, non_finite):
        env = issue_certificate(_report())
        env["report"] = bad
        result = verify_certificate(env)  # must not raise
        assert result["report_binding_valid"] is False
        assert result["ok"] is False


def test_absent_report_keeps_standalone_certificate_valid(monkeypatch):
    """A fully absent `report` key retains standalone-certificate behaviour (binding not applicable)."""
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    env.pop("report", None)
    result = verify_certificate(env)
    assert result["report_binding_valid"] is None
    assert result["ok"] is True


def test_signed_certificate_rejects_replaced_report_even_if_outer_fields_are_replaced(monkeypatch):
    """The report digest must be inside the issuer-signed certificate body."""
    if not _CRYPTO_AVAILABLE:
        import pytest
        pytest.skip("cryptography extra not installed")
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", generate_signing_key())
    original = _report()
    env = issue_certificate(original)
    replacement = copy.deepcopy(original)
    replacement["totals"]["n_bank_lines"] += 1
    env["report"] = replacement
    env["report_sha256"] = "attacker-controlled"  # ignored; no longer a signed field
    result = verify_certificate(env)
    assert result["signature_valid"] is True
    assert result["report_binding_valid"] is False
    assert result["ok"] is False


def test_legacy_envelope_with_unbound_attached_report_is_rejected(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    env["certificate"].pop("report_sha256")
    env["report"] = _report()
    result = verify_certificate(env)
    assert result["report_binding_valid"] is False
    assert result["ok"] is False


def test_tampered_certificate_breaks_the_hash(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    tampered = copy.deepcopy(env)
    tampered["certificate"]["proven_razorpay_count"] = 999999
    v = verify_certificate(tampered)
    assert v["hash_matches"] is False
    assert v["ok"] is False


def test_content_hash_is_deterministic(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    rep = _report()
    assert issue_certificate(rep)["content_sha256"] == issue_certificate(rep)["content_sha256"]


def test_signed_certificate_verifies_and_forgery_is_detected(monkeypatch):
    if not _CRYPTO_AVAILABLE:
        import pytest
        pytest.skip("cryptography extra not installed")
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", generate_signing_key())
    env = issue_certificate(_report())
    assert env["signed"] is True and "signature" in env and "public_key_pem" in env
    v = verify_certificate(env)
    assert v["signature_valid"] is True and v["ok"] is True
    assert v["authenticated"] is True
    # Forge: tamper a signed certificate → signature must fail.
    env["certificate"]["proven_razorpay_count"] = 1
    vf = verify_certificate(env)
    assert vf["signature_valid"] is False
    assert vf["ok"] is False


def test_hashless_or_mismatched_certificate_is_rejected(monkeypatch):
    """Qodo #11: an envelope with no content hash (or a wrong one) must never be reported authentic."""
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    assert verify_certificate({"certificate": {"summary": "x"}})["ok"] is False       # no hash
    assert verify_certificate({"certificate": {"summary": "x"}, "content_sha256": "deadbeef"})["ok"] is False


@pytest.mark.parametrize(
    ("signed", "signature"),
    [
        (True, None),
        (True, ""),
        (False, "bogus"),
        ("true", "bogus"),
    ],
)
def test_signature_declaration_must_match_nonempty_signature(monkeypatch, signed, signature):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    env["signed"] = signed
    if signature is None:
        env.pop("signature", None)
    else:
        env["signature"] = signature
    assert verify_certificate(env)["ok"] is False


def test_invalid_local_signing_configuration_does_not_escape_verifier(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)
    env = issue_certificate(_report())
    env["signed"] = True
    env["signature"] = "bogus"
    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", "invalid-config")
    result = verify_certificate(env)
    assert result["ok"] is False
    assert result["signature_valid"] is False


def test_claimed_signature_that_cannot_be_authenticated_is_invalid(monkeypatch):
    """Qodo #1: a payload that claims a signature but cannot be authenticated against the pinned issuer
    key (here: no issuer key configured) must be invalid, never a passthrough None."""
    if not _CRYPTO_AVAILABLE:
        import pytest
        pytest.skip("cryptography extra not installed")
    monkeypatch.delenv("UNTANGLE_SIGNING_KEY", raising=False)  # no issuer key
    env = issue_certificate(_report())
    env["signature"] = "QUJD"  # base64 'ABC' — a claimed but bogus signature
    v = verify_certificate(env)
    assert v["signature_valid"] is False
    assert v["ok"] is False


def test_forgery_with_attacker_supplied_key_is_rejected(monkeypatch):
    """Qodo #2: signing with the attacker's own key and embedding their public key must NOT verify —
    authentication is against untangle's pinned issuer key, not a key inside the envelope."""
    if not _CRYPTO_AVAILABLE:
        import pytest
        pytest.skip("cryptography extra not installed")
    import base64 as _b64

    from cryptography.hazmat.primitives import hashes as _h
    from cryptography.hazmat.primitives import serialization as _s
    from cryptography.hazmat.primitives.asymmetric import ec as _e

    from engine.certificate import _canonical

    monkeypatch.setenv("UNTANGLE_SIGNING_KEY", generate_signing_key())  # the real issuer
    cert = build_close_certificate(_report())
    body = _canonical(cert)
    attacker = _e.generate_private_key(_e.SECP256R1())  # attacker's own keypair
    forged = {
        "certificate": cert,
        "content_sha256": __import__("hashlib").sha256(body).hexdigest(),  # correct hash
        "signed": True,
        "signature": _b64.b64encode(attacker.sign(body, _e.ECDSA(_h.SHA256()))).decode(),
        "public_key_pem": attacker.public_key().public_bytes(
            _s.Encoding.PEM, _s.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    }
    v = verify_certificate(forged)  # verified against the ISSUER key, not the embedded attacker key
    assert v["signature_valid"] is False
    assert v["ok"] is False


def test_build_close_certificate_on_real_reconciliation():
    """Build report via engine.service.reconcile on data/ (seed 42) and verify certificate contents."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )

    cert = build_close_certificate(report)

    totals = report["totals"]
    assert cert["period_records"] == totals["n_bank_lines"]
    assert cert["proven_razorpay_count"] == totals["by_rail_count"].get("razorpay_settlement", 0)
    assert cert["reconciled_count"] == totals["reconciled_count"]
    assert cert["unresolved_count"] == totals["unresolved_rzp_count"]
    assert cert["exception_count"] == totals["exception_count"]
    assert cert["exceptions_by_reason"] == totals["exceptions_by_reason"]
    assert cert["engine_version"] == report["config"]["engine_version"]
    assert cert["seed"] == 42
    assert cert["audit_root"] == report["audit_root"]

    # All proof packets verified and passed
    assert cert["verification"]["packets_verified"] == len(report["proof_packets"])
    assert cert["verification"]["packets_passed"] == len(report["proof_packets"])
    assert cert["verification"]["packets_verified"] > 0

    # Summary string is present and correctly formatted
    summary = cert["summary"]
    assert summary.startswith("Period closed:")
    assert f"{cert['proven_razorpay_count']} credits proven Razorpay" in summary
    assert "0 unverifiable proof packets." in summary


def test_certificate_determinism():
    """Two calls with the same report dictionary produce identical output."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )
    cert1 = build_close_certificate(report)
    cert2 = build_close_certificate(report)

    assert cert1 == cert2
    assert json.dumps(cert1, sort_keys=True) == json.dumps(cert2, sort_keys=True)


def test_certificate_cli_execution(tmp_path):
    """CLI python -m engine.certificate --run out/report.json prints valid certificate JSON."""
    report = reconcile(
        "data/bank_statement.csv",
        "data/recon_report.json",
        "data/order_ledger.csv",
        no_ai=True,
        seed=42,
    )
    report_file = tmp_path / "test_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f)

    cmd = [sys.executable, "-m", "engine.certificate", "--run", str(report_file)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)

    out_data = json.loads(res.stdout)
    # The CLI now emits the content-hashed envelope; the certificate body is nested under "certificate".
    assert len(out_data["content_sha256"]) == 64
    body = out_data["certificate"]
    assert "summary" in body
    assert "verification" in body
    assert body["proven_razorpay_count"] == report["totals"]["by_rail_count"].get("razorpay_settlement", 0)

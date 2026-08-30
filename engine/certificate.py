"""Period Close Certificate Generator.

Produces a JSON-serializable dictionary summarizing a reconciliation period,
verifying all proof packets and attestation integrity.

CLI usage:
    python -m engine.certificate --run out/report.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from typing import Any

from engine.verifier import verify_report

# Optional asymmetric signing (adapted from the Obliviate erasure-certificate pattern). The core
# stays stdlib-only: signing activates ONLY when the `cryptography` extra is installed AND a signing
# key is configured; otherwise the certificate is still built and content-hashed (tamper-evident),
# just unsigned — anyone can recompute the hash and inspect the bound report's packet checks.
try:  # optional extra: pip install "untangle[crypto]"
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import ec as _ec

    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when the extra is absent
    _CRYPTO_AVAILABLE = False

_SIGNING_KEY_ENV = "UNTANGLE_SIGNING_KEY"  # base64-encoded PEM (PKCS8) ECDSA private key


def _inr(paise: int) -> str:
    """Format paise as standard INR currency string."""
    return f"₹{paise / 100:,.2f}"


def _canonical(obj: Any) -> bytes:
    """Deterministic JSON encoding used for hashing and signing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _signing_key():
    """Load the ECDSA private key from the env (base64 PEM), or None if unavailable/unset."""
    if not _CRYPTO_AVAILABLE:
        return None
    pem = os.environ.get(_SIGNING_KEY_ENV)
    if not pem:
        return None
    try:
        return _ser.load_pem_private_key(base64.b64decode(pem), password=None)
    except Exception:
        return None


def generate_signing_key() -> str:
    """Mint a new base64-PEM ECDSA (P-256) private key to store in $UNTANGLE_SIGNING_KEY."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Signing requires the optional 'crypto' extra: pip install 'untangle[crypto]'")
    key = _ec.generate_private_key(_ec.SECP256R1())
    pem = key.private_bytes(
        _ser.Encoding.PEM, _ser.PrivateFormat.PKCS8, _ser.NoEncryption()
    )
    return base64.b64encode(pem).decode()


def public_key_pem() -> str | None:
    """The PEM public key anyone can verify a signed certificate against (None if unsigned)."""
    key = _signing_key()
    if key is None:
        return None
    return key.public_key().public_bytes(
        _ser.Encoding.PEM, _ser.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def issue_certificate(report: dict) -> dict:
    """Build → content-hash → (optionally) sign a close certificate into a portable envelope:
        {certificate, content_sha256, signature?, public_key_pem?}
    The content hash is always present (tamper-evident); the ECDSA signature is added only when the
    crypto extra is installed and $UNTANGLE_SIGNING_KEY is set. Fully deterministic."""
    cert = build_close_certificate(report)
    # Bind the optional raw report inside the signed/content-hashed certificate body. Keeping this
    # digest outside the body would let an attacker replace both the report and its outer digest.
    cert["report_sha256"] = hashlib.sha256(_canonical(report)).hexdigest()
    body = _canonical(cert)
    envelope: dict[str, Any] = {
        "certificate": cert,
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "signed": False,
        # Honest framing (from the Lethe pattern): by default this is a tamper-evident content hash,
        # not a cryptographic signature — and untangle's real proof is that every verdict is
        # re-derivable from the source files (re-run the verifier), never "trust our attestation".
        "note": (
            "Tamper-evident content hash (SHA-256) over the certificate. Not a cryptographic "
            "signature. Packet checks can be re-run against the attached bound report; this does not "
            "re-audit the original bank, settlement, or ledger source files."
        ),
    }
    key = _signing_key()
    if key is not None:
        sig = key.sign(body, _ec.ECDSA(_hashes.SHA256()))
        envelope["signature"] = base64.b64encode(sig).decode()
        envelope["public_key_pem"] = public_key_pem()
        envelope["signed"] = True
        envelope["note"] = (
            "ECDSA (P-256) signed and tamper-evident. Re-derive the SHA-256 hash and check the "
            "signature against this deployment's pinned issuer key — a tampered field breaks the "
            "hash, a forgery fails the signature. Packet checks can be re-run against the attached "
            "bound report; this does not re-audit the original bank, settlement, or ledger source files."
        )
    return envelope


def verify_certificate(payload: dict) -> dict:
    """Independently verify a close-certificate envelope: re-derive the SHA-256 content hash, re-run
    every proof-packet check, and (when signed) check the ECDSA signature against this deployment's
    pinned issuer key.
    A tampered field breaks the hash; a forged certificate fails the signature. Never raises."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload is not a dict"}
    cert = payload.get("certificate") if isinstance(payload.get("certificate"), dict) else payload
    body = _canonical(cert)
    recomputed = hashlib.sha256(body).hexdigest()
    claimed = payload.get("content_sha256")
    # Qodo #11: a certificate MUST carry a content hash that matches; a missing/mismatched hash fails.
    # (A None-hash must NOT satisfy the final `ok`, or bare envelopes get reported authentic.)
    hash_matches = isinstance(claimed, str) and recomputed == claimed

    # Qodo #1 + #2: a claimed signature must verify TRUE against untangle's OWN pinned issuer key (from
    # $UNTANGLE_SIGNING_KEY / public_key_pem()) — NEVER a key embedded in the untrusted envelope (that
    # would let anyone sign with their own key and claim validity). If a signature is present but cannot
    # be authenticated (no crypto, no configured issuer key, malformed, or mismatch) → invalid, not None.
    signature_valid: bool | None = None
    sig = payload.get("signature")
    if sig:
        issuer_pub = public_key_pem()  # this instance's pinned public key; None if unconfigured
        signature_valid = False
        if _CRYPTO_AVAILABLE and issuer_pub:
            try:
                pub = _ser.load_pem_public_key(issuer_pub.encode())
                pub.verify(base64.b64decode(sig), body, _ec.ECDSA(_hashes.SHA256()))
                signature_valid = True
            except Exception:  # InvalidSignature, malformed key/sig, etc. → not authenticated
                signature_valid = False

    # Independent re-verification of an attached report is useful only when the report is bound to
    # the report that was used at issuance. The raw report is omitted, but its digest is part of the
    # signed/content-hashed certificate body.
    embedded_report = payload.get("report") if isinstance(payload.get("report"), dict) else None
    packets_verified = packets_passed = None
    report_binding_valid: bool | None = None
    if embedded_report is not None:
        expected_report_hash = cert.get("report_sha256")
        report_binding_valid = (
            isinstance(expected_report_hash, str)
            and hashlib.sha256(_canonical(embedded_report)).hexdigest() == expected_report_hash
        )
        results = verify_report(embedded_report)
        pkt = [r for r in results if r.packet_line_key != "report:audit_root"]
        packets_verified = len(pkt)
        packets_passed = sum(1 for r in pkt if r.ok)

    ok = (
        hash_matches
        and (sig is None or signature_valid is True)     # a claimed signature must be valid
        and (report_binding_valid is not False)
        and (packets_passed is None or packets_passed == packets_verified)
    )
    return {
        "ok": bool(ok),
        "content_hash": recomputed,
        "claimed_hash": claimed,
        "hash_matches": hash_matches,
        "signature_valid": signature_valid,
        "signed": bool(sig),
        "authenticated": bool(sig) and signature_valid is True,
        # Issuer-attested packet verification recorded at issue time (Qodo #3: the standalone cert does
        # not embed the full report, so independent re-verification needs `report` supplied above; this
        # surfaces what the issuer attested, clearly distinct from an independent re-run).
        "attested_verification": cert.get("verification"),
        "packets_verified": packets_verified,
        "packets_passed": packets_passed,
        "report_binding_valid": report_binding_valid,
        "summary": cert.get("summary"),
        "audit_root": cert.get("audit_root"),
    }


def build_close_certificate(report: dict) -> dict[str, Any]:
    """Build a period close certificate honest to the underlying report."""
    if not isinstance(report, dict):
        raise ValueError("Report must be a dictionary")

    totals = report.get("totals", {})
    config = report.get("config", {})

    period_records = totals.get("n_bank_lines", 0)

    # Proven Razorpay credits
    by_rail_count = totals.get("by_rail_count", {})
    by_rail_paise = totals.get("by_rail_paise", {})
    proven_rzp_count = by_rail_count.get("razorpay_settlement", 0)
    proven_rzp_paise = by_rail_paise.get("razorpay_settlement", 0)
    proven_rzp_inr = _inr(proven_rzp_paise)

    # Reconciled slice
    reconciled_count = totals.get("reconciled_count", 0)
    reconciled_paise = totals.get("reconciled_paise", 0)
    reconciled_inr = _inr(reconciled_paise)

    # Unresolved slice
    unresolved_count = totals.get("unresolved_rzp_count", 0)
    unresolved_paise = max(0, proven_rzp_paise - reconciled_paise)
    unresolved_inr = _inr(unresolved_paise)

    # Fee GST recoverable
    fee_gst_paise = totals.get("fee_gst_recoverable_paise", 0)
    fee_gst_recoverable_inr = _inr(fee_gst_paise)

    # Exceptions
    exception_count = totals.get("exception_count", 0)
    exceptions_by_reason = dict(totals.get("exceptions_by_reason", {}))

    # Verification block (using verify_report)
    verification_results = verify_report(report)
    # Count packet verification (excluding the report:audit_root result)
    packet_results = [r for r in verification_results if r.packet_line_key != "report:audit_root"]
    packets_verified = len(packet_results)
    packets_passed = sum(1 for r in packet_results if r.ok)

    # Cross-check audit_root format result
    audit_res = next((r for r in verification_results if r.packet_line_key == "report:audit_root"), None)
    audit_root_valid = audit_res.ok if audit_res else False

    engine_version = config.get("engine_version", "0.1.0")
    seed = config.get("seed", 42)
    audit_root = report.get("audit_root", "")

    generated_from_hashes = {
        "audit_root": audit_root,
        "audit_root_valid": audit_root_valid,
        "packets_total": packets_verified,
        "packets_verified": packets_passed,
    }

    unverifiable_count = packets_verified - packets_passed
    summary = (
        f"Period closed: {proven_rzp_count} credits proven Razorpay ({proven_rzp_inr}), "
        f"{unresolved_inr} unresolved pending evidence, "
        f"{unverifiable_count} unverifiable proof packets."
    )

    return {
        "summary": summary,
        "period_records": period_records,
        "proven_razorpay_count": proven_rzp_count,
        "proven_razorpay_inr": proven_rzp_inr,
        "reconciled_count": reconciled_count,
        "reconciled_inr": reconciled_inr,
        "unresolved_count": unresolved_count,
        "unresolved_inr": unresolved_inr,
        "fee_gst_recoverable_inr": fee_gst_recoverable_inr,
        "exception_count": exception_count,
        "exceptions_by_reason": exceptions_by_reason,
        "verification": {
            "packets_verified": packets_verified,
            "packets_passed": packets_passed,
        },
        "engine_version": engine_version,
        "seed": seed,
        "audit_root": audit_root,
        "generated_from_hashes": generated_from_hashes,
    }


def main() -> None:
    """CLI entry point for close certificate generation."""
    parser = argparse.ArgumentParser(description="Generate period close certificate from report JSON")
    parser.add_argument("--run", required=True, help="Path to report JSON")
    args = parser.parse_args()

    try:
        with open(args.run, encoding="utf-8") as f:
            report = json.load(f)
    except Exception as exc:
        print(f"Error loading report from {args.run}: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        cert = build_close_certificate(report)
    except Exception as exc:
        print(f"Error generating close certificate: {exc}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(cert, indent=2))


if __name__ == "__main__":
    main()

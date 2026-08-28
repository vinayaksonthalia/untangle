"""Period Close Certificate Generator.

Produces a JSON-serializable dictionary summarizing a reconciliation period,
verifying all proof packets and attestation integrity.

CLI usage:
    python -m engine.certificate --run out/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from engine.verifier import verify_report


def _inr(paise: int) -> str:
    """Format paise as standard INR currency string."""
    return f"₹{paise / 100:,.2f}"


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

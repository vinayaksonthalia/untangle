"""Model Context Protocol (MCP) Server for untangle.

Exposes read-only, deterministic accounting and reconciliation tools to AI agents
over stdio transport.

All tools are read-only: they analyze financial records, compute attributions,
verify proof packets, generate close certificates, and produce journal exports.
They NEVER move money or mutate underlying financial state.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from engine.attribute import attribute_all
from engine.certificate import issue_certificate
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.journal import JournalEntry, build_journal_entries, to_journal_json, to_tally_xml
from engine.reconcile import reconcile as reconcile_core
from engine.service import reconcile
from engine.verifier import verify_proof_packet as verify_packet_core

# Initialize FastMCP Server
mcp = FastMCP(
    name="untangle",
    instructions=(
        "Untangle Multi-Rail Bank-Credit Attribution & Razorpay Reconciliation Engine. "
        "Provides read-only, mathematically grounded reconciliation, evidence-backed proof packets, "
        "recovery recommendations, close certificates, and balanced double-entry accounting journal vouchers."
    ),
)


# -----------------------------------------------------------------------------
# Caching helpers for deterministic read-only file processing
# -----------------------------------------------------------------------------
@lru_cache(maxsize=16)
def _cached_reconcile(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    _mtime_token: tuple[float, float, float],
) -> dict[str, Any]:
    return reconcile(bank_path, recon_path, ledger_path, no_ai=True, seed=42)


def _get_report(bank_path: str, recon_path: str, ledger_path: str) -> dict[str, Any]:
    """Load and reconcile files, using mtime caching for speed."""
    try:
        t_bank = os.path.getmtime(bank_path)
        t_recon = os.path.getmtime(recon_path)
        t_ledger = os.path.getmtime(ledger_path)
        token = (t_bank, t_recon, t_ledger)
    except Exception:
        token = (0.0, 0.0, 0.0)
    return _cached_reconcile(bank_path, recon_path, ledger_path, token)


@lru_cache(maxsize=16)
def _cached_journal_entries(
    bank_path: str,
    recon_path: str,
    _mtime_token: tuple[float, float],
) -> list[JournalEntry]:
    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    index = ReconIndex(recon_rows)
    attributions = attribute_all(lines, index, 0.55, audit_challenger=True)
    lines_by_key = {ln.key: ln for ln in lines}
    reconciliations, _u, _s = reconcile_core(lines_by_key, attributions, recon_rows)
    return build_journal_entries(reconciliations, recon_rows)


def _get_journal_entries(bank_path: str, recon_path: str) -> list[JournalEntry]:
    try:
        t_bank = os.path.getmtime(bank_path)
        t_recon = os.path.getmtime(recon_path)
        token = (t_bank, t_recon)
    except Exception:
        token = (0.0, 0.0)
    return _cached_journal_entries(bank_path, recon_path, token)


# -----------------------------------------------------------------------------
# MCP Tools
# -----------------------------------------------------------------------------
@mcp.tool()
def reconcile_files(bank_path: str, recon_path: str, ledger_path: str) -> dict[str, Any]:
    """Reconcile bank statement against Razorpay settlement report and order ledger.

    Returns the headline totals and attribution counts (summarized, not the entire raw report).

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.

    Returns:
        Structured dictionary with totals, audit_root, and key reconciliation metrics.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        totals = report.get("totals", {})
        return {
            "ok": True,
            "audit_root": report.get("audit_root"),
            "config": report.get("config"),
            "totals": totals,
            "headline_metrics": {
                "n_bank_lines": totals.get("n_bank_lines", 0),
                "n_recon_rows": totals.get("n_recon_rows", 0),
                "attributed_count": totals.get("attributed", 0),
                "abstained_count": totals.get("abstained", 0),
                "reconciled_count": totals.get("reconciled_count", 0),
                "reconciled_paise": totals.get("reconciled_paise", 0),
                "unresolved_rzp_count": totals.get("unresolved_rzp_count", 0),
                "fee_gst_recoverable_paise": totals.get("fee_gst_recoverable_paise", 0),
                "exception_count": totals.get("exception_count", 0),
                "by_rail_count": totals.get("by_rail_count", {}),
                "by_rail_paise": totals.get("by_rail_paise", {}),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def list_unresolved_cash(bank_path: str, recon_path: str, ledger_path: str) -> dict[str, Any]:
    """List all unresolved bank credits with their rupee amounts and reason codes.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.

    Returns:
        Dictionary containing unresolved credit items, reason codes, and recovery plan summary.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        exceptions = report.get("exceptions", [])
        plan = report.get("recovery_plan") or {}

        items = []
        for exc in exceptions:
            items.append({
                "line_key": exc.get("line_key"),
                "reason_code": exc.get("reason_code"),
                "detail": exc.get("detail"),
                "suggested_action": exc.get("suggested_action"),
            })

        return {
            "ok": True,
            "unresolved_count": len(items),
            "items": items,
            "recovery_summary": {
                "unresolved_paise": plan.get("unresolved_paise", 0),
                "recoverable_if_actioned_paise": plan.get("recoverable_if_actioned_paise", 0),
                "note": plan.get("note"),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def explain_bank_credit(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    line_key: str,
) -> dict[str, Any]:
    """Explain the verdict and evidence for a specific bank credit line_key.

    Includes tie evidence, proof margin, and rejected competing explanations.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.
        line_key: The unique hash key of the bank credit line.

    Returns:
        Structured explanation of the credit verdict and proof details.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)

        # Check proof packets first (for proven Razorpay credits)
        for pkt in report.get("proof_packets", []):
            if pkt.get("line_key") == line_key:
                proof = pkt.get("proof", {})
                challenge = proof.get("challenge") or {}
                return {
                    "ok": True,
                    "line_key": line_key,
                    "verdict": pkt.get("verdict"),
                    "amount_inr": pkt.get("amount_inr"),
                    "narration": pkt.get("narration"),
                    "value_date": pkt.get("value_date"),
                    "reconciled": pkt.get("reconciled"),
                    "fee_gst_recoverable_inr": pkt.get("fee_gst_recoverable_inr"),
                    "proof": {
                        "ties": proof.get("ties", []),
                        "corroboration": proof.get("corroboration", []),
                        "rejected_alternatives": proof.get("rejected_alternatives"),
                        "proof_margin": challenge.get("proof_margin"),
                        "rejected_explanation": challenge.get("rejected_explanation"),
                        "violated_constraints": proof.get("violated_constraints"),
                    },
                    "settlement": pkt.get("settlement"),
                }

        # Check attributions (for non-Razorpay or abstained credits)
        for attr in report.get("attributions", []):
            if attr.get("line_key") == line_key:
                exc = next((e for e in report.get("exceptions", []) if e.get("line_key") == line_key), None)
                return {
                    "ok": True,
                    "line_key": line_key,
                    "verdict": {
                        "rail": attr.get("rail"),
                        "tier": attr.get("tier"),
                        "confidence": attr.get("confidence"),
                        "abstained": attr.get("abstained"),
                    },
                    "evidence": attr.get("evidence", []),
                    "exception": exc,
                    "proof_margin": attr.get("proof_margin"),
                    "competing_explanation": attr.get("competing_explanation"),
                }

        return {
            "ok": False,
            "error": f"Credit line_key '{line_key}' not found in report",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def get_competing_explanations(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    line_key: str,
) -> dict[str, Any]:
    """Get the adversarial challenger's proof margin and rejected competing explanation.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.
        line_key: The unique hash key of the bank credit line.

    Returns:
        Dictionary containing proof margin, rejected explanation, and competing alternatives.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)

        for pkt in report.get("proof_packets", []):
            if pkt.get("line_key") == line_key:
                proof = pkt.get("proof", {})
                challenge = proof.get("challenge") or {}
                return {
                    "ok": True,
                    "line_key": line_key,
                    "rail": pkt.get("verdict", {}).get("rail"),
                    "confidence": pkt.get("verdict", {}).get("confidence"),
                    "proof_margin": challenge.get("proof_margin"),
                    "rejected_explanation": challenge.get("rejected_explanation"),
                    "rejected_alternatives": proof.get("rejected_alternatives"),
                    "violated_constraints": proof.get("violated_constraints"),
                }

        for attr in report.get("attributions", []):
            if attr.get("line_key") == line_key:
                return {
                    "ok": True,
                    "line_key": line_key,
                    "rail": attr.get("rail"),
                    "confidence": attr.get("confidence"),
                    "proof_margin": attr.get("proof_margin"),
                    "rejected_explanation": attr.get("competing_explanation"),
                    "rejected_alternatives": None,
                    "violated_constraints": None,
                }

        return {
            "ok": False,
            "error": f"Credit line_key '{line_key}' not found in report",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def suggest_next_evidence(bank_path: str, recon_path: str, ledger_path: str) -> dict[str, Any]:
    """Get the active recovery plan's ranked next-best actions to recover unresolved credits.

    Actions are ranked by recoverable impact per operational cost.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.

    Returns:
        List of ranked recovery actions with required parameters, cost, and resolvable line keys.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        plan = report.get("recovery_plan") or {}
        return {
            "ok": True,
            "unresolved_paise": plan.get("unresolved_paise", 0),
            "recoverable_if_actioned_paise": plan.get("recoverable_if_actioned_paise", 0),
            "actions": plan.get("actions", []),
            "note": plan.get("note"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def export_proof_packet(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    line_key: str,
) -> dict[str, Any]:
    """Export the full proof packet (US-facing audit receipt) for a single proven credit line_key.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.
        line_key: The unique hash key of the bank credit line.

    Returns:
        The full proof packet dictionary.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        for pkt in report.get("proof_packets", []):
            if pkt.get("line_key") == line_key:
                return {
                    "ok": True,
                    "packet": pkt,
                }
        return {
            "ok": False,
            "error": f"No proof packet found for line_key '{line_key}'",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def verify_proof_packet(packet_json: str | dict) -> dict[str, Any]:
    """Independently verify a proof packet receipt without re-running the pipeline.

    Re-checks report-backed tie signals, reconciliation arithmetic, and proof margin.

    Args:
        packet_json: Proof packet as a dictionary or serialized JSON string.

    Returns:
        Verification result with boolean status and individual check details.
    """
    try:
        if isinstance(packet_json, str):
            try:
                packet = json.loads(packet_json)
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"Invalid JSON string: {exc}",
                }
        elif isinstance(packet_json, dict):
            packet = packet_json
        else:
            return {
                "ok": False,
                "error": f"Expected dict or JSON string, got {type(packet_json).__name__}",
            }

        res = verify_packet_core(packet)
        return {
            "ok": res.ok,
            "packet_line_key": res.packet_line_key,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in res.checks
            ],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def generate_close_certificate(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
) -> dict[str, Any]:
    """Generate a tamper-evident period close certificate envelope.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.

    Returns:
        Close certificate envelope with content hash and optional ECDSA signature.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        envelope = issue_certificate(report)
        return {
            "ok": True,
            "envelope": envelope,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@mcp.tool()
def export_journal_entries(
    bank_path: str,
    recon_path: str,
    ledger_path: str = "",
    format: str = "json",
) -> dict[str, Any]:
    """Export balanced double-entry accounting journal vouchers for all reconciled Razorpay credits.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Optional path to order ledger CSV.
        format: Export format, either 'json' or 'tally_xml'.

    Returns:
        Postable journal vouchers formatted as JSON entries or Tally Prime XML.
    """
    try:
        entries = _get_journal_entries(bank_path, recon_path)
        fmt = format.lower().strip()

        if fmt == "tally_xml":
            xml_content = to_tally_xml(entries)
            return {
                "ok": True,
                "format": "tally_xml",
                "entry_count": len(entries),
                "content": xml_content,
            }
        elif fmt == "json":
            return {
                "ok": True,
                "format": "json",
                "entry_count": len(entries),
                "entries": to_journal_json(entries),
            }
        else:
            return {
                "ok": False,
                "error": f"Unsupported format '{format}'. Use 'json' or 'tally_xml'.",
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


# -----------------------------------------------------------------------------
# Server Entry Point
# -----------------------------------------------------------------------------
def main() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

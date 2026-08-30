"""Model Context Protocol (MCP) Server for untangle.

Exposes read-only, deterministic accounting and reconciliation tools to AI agents
over stdio transport.

All tools are read-only: they analyze financial records, compute attributions,
verify proof packets, generate close certificates, and produce journal exports.
They NEVER move money or mutate underlying financial state.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from engine.attribute import attribute_all
from engine.certificate import issue_certificate
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.investigate import investigate
from engine.journal import JournalEntry, build_journal_entries, to_journal_json, to_tally_xml
from engine.reconcile import reconcile as reconcile_core
from engine.service import reconcile_bytes
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

# Streamable-HTTP transport configuration
mcp.settings.streamable_http_path = "/"
# Stateless: no per-client session state accumulates in the container — correct for a public,
# read-only endpoint and simpler for hosted clients (no session-id round-trip to maintain).
mcp.settings.stateless_http = True
mcp.settings.transport_security.enable_dns_rebinding_protection = True

# Whitelist allowed hosts/origins for DNS-rebinding protection (env-driven with safe defaults).
# `UNTANGLE_MCP_ALLOWED_HOSTS` (comma-separated) is the explicit override for any deploy host / custom
# domain. On Render, RENDER_EXTERNAL_HOSTNAME is injected automatically — pick it up so the real deploy
# hostname is accepted without manual config.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
_env_hosts = os.environ.get("UNTANGLE_MCP_ALLOWED_HOSTS", "")
if _env_hosts:
    mcp.settings.transport_security.allowed_hosts = [h.strip() for h in _env_hosts.split(",") if h.strip()]
else:
    mcp.settings.transport_security.allowed_hosts = [
        "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*",
        "0.0.0.0", "0.0.0.0:*", "testserver", "testserver:*",
        "untangle.onrender.com", "untangle.onrender.com:*",
    ]
    if _render_host:
        mcp.settings.transport_security.allowed_hosts += [_render_host, f"{_render_host}:*"]

_env_origins = os.environ.get("UNTANGLE_MCP_ALLOWED_ORIGINS", "")
if _env_origins:
    mcp.settings.transport_security.allowed_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
else:
    mcp.settings.transport_security.allowed_origins = [
        "http://localhost", "http://localhost:*", "http://127.0.0.1", "http://127.0.0.1:*",
        "https://claude.ai", "https://chatgpt.com", "https://untangle.onrender.com",
    ]
    if _render_host:
        mcp.settings.transport_security.allowed_origins.append(f"https://{_render_host}")


# -----------------------------------------------------------------------------
# Sandbox: confine file access when exposed over the public HTTP surface.
# -----------------------------------------------------------------------------
# The tools take file PATHS, which is fine for LOCAL stdio (a trusted agent on the user's machine).
# But over the PUBLIC remote endpoint an unauthenticated caller must NOT be able to open arbitrary
# server files. When UNTANGLE_MCP_SANDBOX is on (set by the web app / --http surface), every path is
# confined to the bundled demo-data directory. Real user data goes through the web BYOD upload, not
# the public MCP.
_DATA_DIR = os.path.realpath(
    os.environ.get("UNTANGLE_MCP_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
)
# Cap the one tool that parses a caller-supplied JSON string (verify_proof_packet) — a public endpoint
# must not be forced to parse an unbounded body.
_MAX_PACKET_JSON_BYTES = 512 * 1024


def _sandboxed() -> bool:
    return os.environ.get("UNTANGLE_MCP_SANDBOX", "").strip().lower() in ("1", "true", "yes", "on")


def _safe_path(p: str) -> str:
    """In sandbox mode, confine a caller-supplied path to the demo-data dir; otherwise pass through."""
    if not _sandboxed():
        return p
    rp = os.path.realpath(p)
    if os.path.commonpath([rp, _DATA_DIR]) != _DATA_DIR:
        raise ValueError(
            "path is outside the allowed data directory — the remote MCP is sandboxed to the bundled "
            "demo dataset; upload your own files through the web app instead."
        )
    return rp


# -----------------------------------------------------------------------------
# Caching helpers for deterministic read-only file processing
# -----------------------------------------------------------------------------
def _content_token(*paths: str) -> tuple[str, ...]:
    """A per-file SHA-256 content token for the caches. mtime alone is unsafe: replacing a file while
    preserving its mtime would serve a stale reconciliation from the process-global cache (the trusted
    stdio MCP accepts caller-supplied stable paths). Keying on content means identical inputs still hit
    and any change misses (Qodo full-tree #6)."""
    tokens: list[str] = []
    for path in paths:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
            tokens.append(h.hexdigest())
        except OSError:
            tokens.append("")  # unreadable → distinct token; the loader surfaces the real error
    return tuple(tokens)


def _snapshot_inputs(*paths: str) -> tuple[tuple[bytes, ...], tuple[str, ...]]:
    """Read each input once and derive cache tokens from those exact immutable bytes."""
    contents: list[bytes] = []
    tokens: list[str] = []
    for path in paths:
        with open(path, "rb") as fh:
            content = fh.read()
        contents.append(content)
        tokens.append(hashlib.sha256(content).hexdigest())
    return tuple(contents), tuple(tokens)


@lru_cache(maxsize=16)
def _cached_reconcile(
    bank_bytes: bytes,
    recon_bytes: bytes,
    ledger_bytes: bytes,
    _content_token: tuple[str, str, str],
) -> dict[str, Any]:
    return reconcile_bytes(bank_bytes, recon_bytes, ledger_bytes, no_ai=True, seed=42)


def _get_report(bank_path: str, recon_path: str, ledger_path: str) -> dict[str, Any]:
    """Load and reconcile files, cached by file CONTENT so replacing a file (even with the same mtime)
    never returns a stale report."""
    bank_path, recon_path, ledger_path = _safe_path(bank_path), _safe_path(recon_path), _safe_path(ledger_path)
    snapshots, token = _snapshot_inputs(bank_path, recon_path, ledger_path)
    return _cached_reconcile(*snapshots, token)


@lru_cache(maxsize=16)
def _cached_journal_entries(
    bank_bytes: bytes,
    recon_bytes: bytes,
    _content_token: tuple[str, str],
) -> list[JournalEntry]:
    with tempfile.TemporaryDirectory(prefix="untangle-journal-") as tmpdir:
        bank_path = os.path.join(tmpdir, "bank_statement.csv")
        recon_path = os.path.join(tmpdir, "recon_report.json")
        for path, content in ((bank_path, bank_bytes), (recon_path, recon_bytes)):
            with open(path, "wb") as fh:
                fh.write(content)
        lines = load_bank(bank_path)
        recon_rows = load_recon(recon_path)
        index = ReconIndex(recon_rows)
        attributions = attribute_all(lines, index, 0.55, audit_challenger=True)
        lines_by_key = {ln.key: ln for ln in lines}
        reconciliations, _u, _s = reconcile_core(lines_by_key, attributions, recon_rows)
        return build_journal_entries(reconciliations, recon_rows)


def _get_journal_entries(bank_path: str, recon_path: str) -> list[JournalEntry]:
    bank_path, recon_path = _safe_path(bank_path), _safe_path(recon_path)
    snapshots, token = _snapshot_inputs(bank_path, recon_path)
    return _cached_journal_entries(*snapshots, token)


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
            if len(packet_json.encode("utf-8")) > _MAX_PACKET_JSON_BYTES:
                return {
                    "ok": False,
                    "error": f"packet JSON exceeds the {_MAX_PACKET_JSON_BYTES // 1024} KB limit",
                    "error_type": "PayloadTooLarge",
                }
            try:
                packet = json.loads(packet_json)
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"Invalid JSON string: {exc}",
                }
        elif isinstance(packet_json, dict):
            # Bound dict inputs too — a caller can otherwise pass an arbitrarily large object.
            if len(json.dumps(packet_json, default=str).encode("utf-8")) > _MAX_PACKET_JSON_BYTES:
                return {
                    "ok": False,
                    "error": f"packet exceeds the {_MAX_PACKET_JSON_BYTES // 1024} KB limit",
                    "error_type": "PayloadTooLarge",
                }
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


@mcp.tool()
def investigate_variance(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    line_key: str,
) -> dict[str, Any]:
    """Investigate the root-cause of variance for an unresolved or recon-failure bank credit.

    Returns the deterministic root-cause diagnosis, reasoning trace, candidates tried,
    and a balanced corrective double-entry journal draft.

    Args:
        bank_path: Path to bank statement CSV.
        recon_path: Path to Razorpay settlement recon report JSON.
        ledger_path: Path to order ledger CSV.
        line_key: The unique hash key of the bank credit line.

    Returns:
        Investigation dictionary containing root_cause, confidence, reasoning_trace,
        candidates_tried, and corrective_entry draft.
    """
    try:
        report = _get_report(bank_path, recon_path, ledger_path)
        investigations = report.get("investigations", [])
        for inv in investigations:
            if inv.get("line_key") == line_key:
                return {
                    "ok": True,
                    "investigation": inv,
                }

        # If not pre-computed in report, investigate on the fly
        lines = load_bank(_safe_path(bank_path))
        recon_rows = load_recon(_safe_path(recon_path))
        index = ReconIndex(recon_rows)
        attributions = attribute_all(lines, index, 0.55, audit_challenger=True)
        lines_by_key = {ln.key: ln for ln in lines}
        reconciliations, _u, _s = reconcile_core(lines_by_key, attributions, recon_rows)
        exceptions = report.get("exceptions", [])

        line = lines_by_key.get(line_key)
        if line is None:
            return {
                "ok": False,
                "error": f"Bank credit line '{line_key}' not found",
                "error_type": "LineNotFound",
            }

        attr = next((a for a in attributions if a.line_key == line_key), None)
        rec = next((r for r in reconciliations if r.line_key == line_key), None)
        exc = next((e for e in exceptions if e.get("line_key") == line_key), None)

        inv_res = investigate(
            line=line,
            attribution=attr,
            reconciliation=rec,
            recon_rows=recon_rows,
            index=index,
            exception=exc,
        )
        return {
            "ok": True,
            "investigation": inv_res.to_dict(),
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
    """Run the MCP server via stdio (default) or streamable-HTTP transport."""
    import argparse

    parser = argparse.ArgumentParser(description="untangle read-only MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run remote streamable-HTTP transport instead of stdio",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface for HTTP transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8081,
        help="Port for HTTP transport (default: 8081)",
    )
    args = parser.parse_args()

    if args.http:
        # A standalone HTTP server is a PUBLIC surface — FAIL CLOSED: force the sandbox on regardless of
        # any inherited env value, so it can never expose arbitrary server files. stdio (below) stays
        # unsandboxed: it is a trusted local process on the user's own machine.
        os.environ["UNTANGLE_MCP_SANDBOX"] = "1"
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

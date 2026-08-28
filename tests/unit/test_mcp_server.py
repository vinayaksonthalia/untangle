"""Unit tests for the MCP Server tools (mcp_server.py).

Tests each tool handler function directly over data/ without requiring a live stdio MCP transport.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp.server.fastmcp")  # needs the optional [mcp] extra (v1 API); skip cleanly otherwise

from mcp_server import (  # noqa: E402  — imported after the importorskip guard, by design
    explain_bank_credit,
    export_journal_entries,
    export_proof_packet,
    generate_close_certificate,
    get_competing_explanations,
    list_unresolved_cash,
    reconcile_files,
    suggest_next_evidence,
    verify_proof_packet,
)

_BANK_PATH = "data/bank_statement.csv"
_RECON_PATH = "data/recon_report.json"
_LEDGER_PATH = "data/order_ledger.csv"
_KNOWN_RZP_KEY = "k_9f8dafbd274120b1"


def test_reconcile_files():
    """reconcile_files returns headline totals and attribution summaries."""
    res = reconcile_files(_BANK_PATH, _RECON_PATH, _LEDGER_PATH)
    assert res["ok"] is True
    assert "audit_root" in res
    assert len(res["audit_root"]) == 64
    assert res["totals"]["n_bank_lines"] == 294
    assert res["headline_metrics"]["reconciled_count"] == 91
    assert res["headline_metrics"]["unresolved_rzp_count"] == 12


def test_list_unresolved_cash():
    """list_unresolved_cash returns exception records with reason codes and suggested actions."""
    res = list_unresolved_cash(_BANK_PATH, _RECON_PATH, _LEDGER_PATH)
    assert res["ok"] is True
    assert res["unresolved_count"] > 0
    assert len(res["items"]) == res["unresolved_count"]
    first = res["items"][0]
    assert "line_key" in first
    assert "reason_code" in first
    assert "detail" in first
    assert "suggested_action" in first
    assert "recovery_summary" in res


def test_explain_bank_credit_known_rzp():
    """explain_bank_credit returns verdict, ties, and proof margin for a proven credit."""
    res = explain_bank_credit(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, _KNOWN_RZP_KEY)
    assert res["ok"] is True
    assert res["line_key"] == _KNOWN_RZP_KEY
    assert res["verdict"]["rail"] == "razorpay_settlement"
    assert len(res["proof"]["ties"]) > 0
    assert res["proof"]["proof_margin"] > 0
    assert res["reconciled"] is True


def test_explain_bank_credit_not_found():
    """explain_bank_credit returns structured error for non-existent line_key."""
    res = explain_bank_credit(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, "k_non_existent_key_123")
    assert res["ok"] is False
    assert "not found" in res["error"].lower()


def test_get_competing_explanations():
    """get_competing_explanations returns challenger proof margin and rejected explanation."""
    res = get_competing_explanations(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, _KNOWN_RZP_KEY)
    assert res["ok"] is True
    assert res["line_key"] == _KNOWN_RZP_KEY
    assert res["rail"] == "razorpay_settlement"
    assert res["proof_margin"] > 0
    assert "rejected_alternatives" in res


def test_suggest_next_evidence():
    """suggest_next_evidence returns recovery plan ranked actions."""
    res = suggest_next_evidence(_BANK_PATH, _RECON_PATH, _LEDGER_PATH)
    assert res["ok"] is True
    assert "actions" in res
    assert len(res["actions"]) > 0
    act0 = res["actions"][0]
    assert "action_type" in act0
    assert "gain_per_cost" in act0
    assert "resolves" in act0


def test_export_proof_packet():
    """export_proof_packet returns the single proof packet receipt."""
    res = export_proof_packet(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, _KNOWN_RZP_KEY)
    assert res["ok"] is True
    pkt = res["packet"]
    assert pkt["line_key"] == _KNOWN_RZP_KEY
    assert pkt["verdict"]["rail"] == "razorpay_settlement"
    assert "proof" in pkt


def test_verify_proof_packet_tool():
    """verify_proof_packet verifies dict or JSON string inputs."""
    # 1. Export valid packet and verify as dict
    exp_res = export_proof_packet(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, _KNOWN_RZP_KEY)
    pkt_dict = exp_res["packet"]

    res_dict = verify_proof_packet(pkt_dict)
    assert res_dict["ok"] is True
    assert res_dict["packet_line_key"] == _KNOWN_RZP_KEY
    assert len(res_dict["checks"]) >= 3
    assert all(c["passed"] for c in res_dict["checks"])

    # 2. Verify as serialized JSON string
    res_str = verify_proof_packet(json.dumps(pkt_dict))
    assert res_str["ok"] is True

    # 3. Verify corrupted / tampered packet fails
    corrupted = dict(pkt_dict)
    corrupted["proof"] = {"ties": []}  # empty ties fails check
    res_bad = verify_proof_packet(corrupted)
    assert res_bad["ok"] is False


def test_generate_close_certificate():
    """generate_close_certificate returns the signed/hashed envelope."""
    res = generate_close_certificate(_BANK_PATH, _RECON_PATH, _LEDGER_PATH)
    assert res["ok"] is True
    envelope = res["envelope"]
    assert "certificate" in envelope
    assert "content_sha256" in envelope
    assert len(envelope["content_sha256"]) == 64
    cert = envelope["certificate"]
    assert cert["proven_razorpay_count"] == 103
    assert cert["reconciled_count"] == 91
    assert "summary" in cert


def test_export_journal_entries_json():
    """export_journal_entries in JSON format returns balanced double-entry vouchers."""
    res = export_journal_entries(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, format="json")
    assert res["ok"] is True
    assert res["format"] == "json"
    assert res["entry_count"] == 91
    assert len(res["entries"]) == 91

    entry0 = res["entries"][0]
    assert entry0["balanced"] is True
    assert len(entry0["lines"]) >= 2


def test_export_journal_entries_tally_xml():
    """export_journal_entries in tally_xml format returns valid Tally Prime XML."""
    res = export_journal_entries(_BANK_PATH, _RECON_PATH, _LEDGER_PATH, format="tally_xml")
    assert res["ok"] is True
    assert res["format"] == "tally_xml"
    assert res["entry_count"] == 91
    xml_content = res["content"]
    assert xml_content.startswith("<ENVELOPE>")
    assert "<TALLYREQUEST>Import Data</TALLYREQUEST>" in xml_content
    assert "</ENVELOPE>" in xml_content


def test_error_handling_invalid_paths():
    """Tools return structured errors when given nonexistent paths without raising unhandled exceptions."""
    res = reconcile_files("invalid/bank.csv", "invalid/recon.json", "invalid/ledger.csv")
    assert res["ok"] is False
    assert "error" in res
    assert "error_type" in res

    res_journal = export_journal_entries("invalid/bank.csv", "invalid/recon.json", format="unknown_format")
    assert res_journal["ok"] is False
    assert "error" in res_journal

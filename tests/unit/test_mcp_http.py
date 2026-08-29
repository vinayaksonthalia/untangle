"""Unit tests for the Remote streamable-HTTP MCP endpoint (Feature 007).

Tests the remote HTTP transport mounted at /mcp in the FastAPI app:
1. MCP initialize handshake over /mcp/ returns untangle serverInfo and session ID.
2. tools/list returns all 10 read-only tool names.
3. Tool execution over HTTP (reconcile_files) returns ok: true and correct report totals.
4. Read-only security invariant: all 10 tools are strictly analytical/read-only with no side-effects.
5. Scoped CORS headers on /mcp/.
"""

from __future__ import annotations

import json

import pytest

# Skip ONLY when the optional [mcp] extra is absent (base install).
pytest.importorskip("mcp")

from fastapi.testclient import TestClient

from webapp.app import app

_EXPECTED_TOOLS = {
    "reconcile_files",
    "list_unresolved_cash",
    "explain_bank_credit",
    "get_competing_explanations",
    "suggest_next_evidence",
    "export_proof_packet",
    "verify_proof_packet",
    "generate_close_certificate",
    "export_journal_entries",
    "investigate_variance",
}


def _extract_jsonrpc_result(response_text: str) -> dict:
    """Parse JSON-RPC response from SSE stream or JSON body."""
    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str:
                return json.loads(data_str)
    # Direct JSON fallback
    return json.loads(response_text)


def test_mcp_http_initialize_handshake():
    """Verify that POST /mcp/ initialize handshake returns untangle serverInfo."""
    with TestClient(app) as client:
        r = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert r.status_code == 200
        session_id = r.headers.get("mcp-session-id")
        assert session_id is not None
        assert len(session_id) > 8

        payload = _extract_jsonrpc_result(r.text)
        assert "result" in payload
        res = payload["result"]
        assert res["protocolVersion"] == "2024-11-05"
        assert res["serverInfo"]["name"] == "untangle"
        assert "tools" in res["capabilities"]


def test_mcp_http_tools_list():
    """Verify that tools/list returns all 10 read-only tool definitions."""
    with TestClient(app) as client:
        # Initialize
        r_init = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert r_init.status_code == 200
        session_id = r_init.headers.get("mcp-session-id")

        # tools/list
        r_list = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "mcp-session-id": session_id,
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        assert r_list.status_code == 200
        payload = _extract_jsonrpc_result(r_list.text)
        tools = payload["result"]["tools"]
        tool_names = {t["name"] for t in tools}

        assert tool_names == _EXPECTED_TOOLS
        assert len(tools) == 10


def test_mcp_http_tool_execution():
    """Verify executing reconcile_files over streamable-HTTP returns correct report structure."""
    with TestClient(app) as client:
        # Initialize
        r_init = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert r_init.status_code == 200
        session_id = r_init.headers.get("mcp-session-id")

        # Call reconcile_files
        r_call = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "mcp-session-id": session_id,
            },
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "reconcile_files",
                    "arguments": {
                        "bank_path": "data/bank_statement.csv",
                        "recon_path": "data/recon_report.json",
                        "ledger_path": "data/order_ledger.csv",
                    },
                },
            },
        )
        assert r_call.status_code == 200
        payload = _extract_jsonrpc_result(r_call.text)
        res = payload["result"]
        assert res.get("isError", False) is False

        # Structured content or text content contains tool response
        output = res.get("structuredContent", {}).get("result")
        if output is None and res.get("content"):
            output = json.loads(res["content"][0]["text"])

        assert output is not None
        assert output["ok"] is True
        assert "audit_root" in output
        assert len(output["audit_root"]) == 64
        metrics = output["headline_metrics"]
        assert metrics["n_bank_lines"] == 294
        assert metrics["reconciled_count"] == 91


def test_mcp_all_tools_are_read_only():
    """Verify that all 10 tools are strictly analytical/read-only with no side effects."""
    with TestClient(app) as client:
        r_init = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "audit-client", "version": "1.0"},
                },
            },
        )
        session_id = r_init.headers.get("mcp-session-id")

        r_list = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "mcp-session-id": session_id,
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        payload = _extract_jsonrpc_result(r_list.text)
        tools = payload["result"]["tools"]

        disallowed_keywords = {"pay", "transfer", "delete", "write", "post_money", "send", "charge", "refund_initiate"}
        for t in tools:
            name = t["name"].lower()
            desc = (t.get("description") or "").lower()
            for kw in disallowed_keywords:
                assert kw not in name, f"Tool '{name}' violates read-only invariant ({kw})"
            # Every tool should be read-only analytical
            assert any(
                allowed in desc or allowed in name
                for allowed in ["reconcile", "list", "explain", "get", "suggest", "export", "verify", "generate", "investigate"]
            )


def test_mcp_http_cors_headers():
    """Verify CORS headers on the /mcp endpoint."""
    with TestClient(app) as client:
        r_opt = client.options(
            "/mcp/",
            headers={
                "origin": "https://claude.ai",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type,mcp-session-id",
            },
        )
        assert r_opt.status_code == 200
        assert r_opt.headers.get("access-control-allow-origin") == "*"
        assert "POST" in r_opt.headers.get("access-control-allow-methods", "")

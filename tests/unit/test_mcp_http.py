"""Unit tests for the Remote streamable-HTTP MCP endpoint (Feature 007).

Tests the remote HTTP transport mounted at /mcp in the FastAPI app:
1. MCP initialize handshake over /mcp/ returns untangle serverInfo.
2. tools/list returns all 12 read-only tool names.
3. Tool execution over HTTP (reconcile_files) returns ok: true against the bundled demo data.
4. Read-only security invariant: all 12 tools are strictly analytical/read-only.
5. SANDBOX: a caller-supplied path outside the demo dir is rejected (no arbitrary server-file read).
6. Scoped CORS on /mcp aligned with the MCP origin allowlist.

A SINGLE module-scoped client is used so the FastMCP session manager runs exactly once (the app is
stateless_http, so no per-client state accumulates and we never re-enter the lifespan).
"""

from __future__ import annotations

import json

import pytest

# Skip ONLY when the optional [mcp] extra is absent (base install).
pytest.importorskip("mcp")

from fastapi.testclient import TestClient  # noqa: E402

from webapp.app import app  # noqa: E402

_EXPECTED_TOOLS = {
    "reconcile_files", "reconcile_sample", "list_unresolved_cash", "sample_unresolved_cash",
    "explain_bank_credit", "get_competing_explanations",
    "suggest_next_evidence", "export_proof_packet", "verify_proof_packet", "generate_close_certificate",
    "export_journal_entries", "investigate_variance",
}
_INIT_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _parse(text: str) -> dict:
    """Parse a JSON-RPC response from an SSE stream or a plain JSON body."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            body = line[len("data:"):].strip()
            if body:
                return json.loads(body)
    return json.loads(text)


def _initialize(client) -> str | None:
    r = client.post("/mcp/", headers=_INIT_HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "test-client", "version": "1.0"}},
    })
    assert r.status_code == 200
    return r.headers.get("mcp-session-id")  # may be None in stateless mode


def _rpc(client, method, params, session_id, req_id):
    headers = dict(_INIT_HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    r = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": req_id, "method": method, "params": params,
    })
    assert r.status_code == 200, r.text
    return _parse(r.text)


def test_mcp_http_initialize_handshake(client):
    r = client.post("/mcp/", headers=_INIT_HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "test-client", "version": "1.0"}},
    })
    assert r.status_code == 200
    res = _parse(r.text)["result"]
    assert res["protocolVersion"] == "2024-11-05"
    assert res["serverInfo"]["name"] == "untangle"
    assert "tools" in res["capabilities"]


def test_mcp_http_tools_list(client):
    sid = _initialize(client)
    payload = _rpc(client, "tools/list", {}, sid, 2)
    tool_names = {t["name"] for t in payload["result"]["tools"]}
    assert tool_names == _EXPECTED_TOOLS
    assert len(payload["result"]["tools"]) == 12


def test_mcp_http_tool_execution(client):
    sid = _initialize(client)
    payload = _rpc(client, "tools/call", {
        "name": "reconcile_files",
        "arguments": {"bank_path": "data/bank_statement.csv", "recon_path": "data/recon_report.json",
                      "ledger_path": "data/order_ledger.csv"},
    }, sid, 3)
    res = payload["result"]
    assert res.get("isError", False) is False
    output = res.get("structuredContent", {}).get("result")
    if output is None and res.get("content"):
        output = json.loads(res["content"][0]["text"])
    assert output["ok"] is True
    assert len(output["audit_root"]) == 64
    assert output["headline_metrics"]["n_bank_lines"] == 294
    assert output["headline_metrics"]["reconciled_count"] == 91


def test_mcp_http_rejects_paths_outside_sandbox(client):
    """Security: over the public HTTP surface the tools are sandboxed to the demo dir — a caller path
    outside it (e.g. an attempt to read a server file) must be rejected, not opened."""
    sid = _initialize(client)
    payload = _rpc(client, "tools/call", {
        "name": "reconcile_files",
        "arguments": {"bank_path": "/etc/passwd", "recon_path": "data/recon_report.json",
                      "ledger_path": "data/order_ledger.csv"},
    }, sid, 4)
    res = payload["result"]
    output = res.get("structuredContent", {}).get("result")
    if output is None and res.get("content"):
        output = json.loads(res["content"][0]["text"])
    assert output["ok"] is False
    assert "allowed data directory" in output["error"]


def test_mcp_all_tools_are_read_only(client):
    sid = _initialize(client)
    tools = _rpc(client, "tools/list", {}, sid, 5)["result"]["tools"]
    disallowed = {"pay", "transfer", "delete", "write", "post_money", "send", "charge", "refund_initiate"}
    for t in tools:
        name = t["name"].lower()
        for kw in disallowed:
            assert kw not in name, f"Tool '{name}' violates read-only invariant ({kw})"


def test_mcp_http_cors_aligned_with_allowlist(client):
    """CORS must agree with the MCP origin allowlist — a listed origin (claude.ai) is allowed, so a
    browser client that clears preflight also clears the MCP handler (no 'CORS yes, MCP no' mismatch)."""
    r = client.options("/mcp/", headers={
        "origin": "https://claude.ai",
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type,mcp-session-id",
    })
    assert r.status_code == 200
    acao = r.headers.get("access-control-allow-origin")
    assert acao in ("https://claude.ai", "*")
    assert "POST" in r.headers.get("access-control-allow-methods", "")

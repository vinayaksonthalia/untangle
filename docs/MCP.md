# Model Context Protocol (MCP) Server (Feature 007)

untangle exposes its multi-rail attribution, settlement reconciliation, proof verification, and accounting
journal engine via the **Model Context Protocol (MCP)** across two complementary transports:

1. **Remote Streamable-HTTP (`/mcp`)** — hosted at `https://<app-host>/mcp`, enabling **zero-install connection**
   for hosted agent platforms (ChatGPT, claude.ai, Claude Code).
2. **Local Stdio (`untangle-mcp`)** — local subprocess transport for desktop environments (Cursor, Claude Desktop,
   Windsurf, VS Code).

---

## 1. Security Architecture & Invariants

- **Strictly Read-Only**: Every tool in untangle is analytical and read-only. The server analyzes files, derives
  mathematical attributions, verifies proof receipts, and drafts journal proposals. It **never writes**, **never
  mutates financial state**, and **never moves money**.
- **Sandboxed file access (public endpoint)**: the tools take file *paths*. Over the public HTTP surface an
  unauthenticated caller must not be able to open arbitrary server files, so when `UNTANGLE_MCP_SANDBOX=1` (set
  automatically by the web app) every path is confined to the bundled demo-data directory
  (`UNTANGLE_MCP_DATA_DIR`, default `data/`); a path outside it is rejected. **The remote MCP runs against the
  demo dataset** — to reconcile your *own* files, use the web upload (BYOD), not the public MCP. Local `stdio`
  (a trusted agent on your machine) is unsandboxed.
- **Stateless**: `stateless_http=True` — no per-client session state accumulates in the container; hosted clients
  need not maintain a session across calls.
- **DNS-Rebinding Protection**: streamable-HTTP keeps Host validation enabled; set the deploy host(s) via
  `UNTANGLE_MCP_ALLOWED_HOSTS` and browser origins via `UNTANGLE_MCP_ALLOWED_ORIGINS` (comma-separated). On Render,
  set `UNTANGLE_MCP_ALLOWED_HOSTS` to your actual app hostname.
- **Scoped CORS**: cross-origin requests to `/mcp` are allowed for the configured origins (aligned with the MCP
  origin allowlist so preflight and the MCP handler agree), no credentials.
- **Bounded input**: `verify_proof_packet` caps the caller-supplied JSON at 512 KB.

---

## 2. Quick Connection Guide

### Option A: Remote Hosted Agent (ChatGPT / claude.ai / Claude Code)

Add untangle as a remote MCP server using the streamable-HTTP endpoint:

- **Server URL**: `https://<your-deployed-app-url>/mcp` (e.g. `https://untangle.onrender.com/mcp`)
- **Transport**: Streamable HTTP (SSE)
- **Auth**: None required (public read-only)

#### Claude Code (CLI)
```bash
claude mcp add untangle -- https://<your-deployed-app-url>/mcp
```

#### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "untangle-remote": {
      "url": "https://<your-deployed-app-url>/mcp"
    }
  }
}
```

---

### Option B: Local Subprocess (`untangle-mcp` via stdio)

Run untangle locally within your environment:

#### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "untangle": {
      "command": "untangle-mcp"
    }
  }
}
```

#### Standalone HTTP Local Server
To run a dedicated local HTTP MCP server on custom port:
```bash
untangle-mcp --http --host 127.0.0.1 --port 8081
```

---

## 3. Tool Catalog (10 Read-Only Tools)

> **On the hosted/remote MCP, start with `reconcile_sample`.** The path-based tools require file
> paths, which the public server's sandbox confines to its bundled data dir — so for a zero-setup
> demo call `reconcile_sample` (no arguments; runs untangle's built-in demo, the same run the web
> app serves at `/try-sample`) and `sample_unresolved_cash`. To reconcile your **own** files, use
> the local `stdio` server (`untangle-mcp`) or the web upload.

| Tool Name | Description | Output |
|---|---|---|
| `reconcile_sample` | Reconciles untangle's built-in demo dataset — **no file paths** (works on the hosted MCP). | Headline metrics, counts, and SHA-256 audit root. |
| `sample_unresolved_cash` | Lists the demo's unresolved credits — **no file paths** (hosted-MCP companion to `list_unresolved_cash`). | Exception records & recovery items. |
| `reconcile_files` | Reconciles bank statement against settlement report and order ledger. | Headline metrics, counts, and SHA-256 audit root. |
| `list_unresolved_cash` | Lists unresolved bank credits with rupee value, reason codes, and recovery actions. | Exception records & recovery items. |
| `explain_bank_credit` | Breaks down credit verdict, tie signals, challenger margin, and settlement coverage. | Credit explanation & proof margin. |
| `get_competing_explanations` | Returns adversarial challenger's rejected explanation and violated constraints. | Challenger audit trail. |
| `suggest_next_evidence` | Returns Active Recovery Controller's ranked next-best actions sorted by ROI. | Ranked recovery actions. |
| `export_proof_packet` | Returns the complete tamper-evident proof packet receipt for a credit. | JSON proof packet receipt. |
| `verify_proof_packet` | Independently validates a proof packet receipt (passed as dict or JSON string). | Verification check breakdown. |
| `generate_close_certificate` | Issues a signed/content-hashed period close certificate envelope. | Verifiable close certificate. |
| `export_journal_entries` | Generates balanced double-entry accounting journal vouchers. | Tally Prime XML or JSON entries. |
| `investigate_variance` | Diagnoses root-cause of reconciliation variances deterministically with reasoning trace. | Root-cause diagnosis & corrective draft. |

---

## 4. Example Remote Tool Request

### 1. Initialize Handshake
```http
POST /mcp/ HTTP/1.1
Host: untangle.onrender.com
Accept: application/json, text/event-stream
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "claude-ai", "version": "1.0"}
  }
}
```

### 2. Response
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
mcp-session-id: 8c23baa4f0c6481abd347ad88ab8423d

event: message
data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"untangle","version":"1.29.0"}}}
```

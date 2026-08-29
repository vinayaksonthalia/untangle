# Feature 007 — Remote (streamable-HTTP) MCP endpoint (Antigravity hand-off spec)

> **Build spec for Antigravity.** Author: Claude (design + review). Build on a feature branch, open a PR,
> Claude runs `/review`, fixes findings, **manual** merge. Do NOT push to main. Do NOT auto-merge.
>
> Read [docs/BUILD_PLAN.md](../../docs/BUILD_PLAN.md) §3 (#2) and §4a first.

---

## 1. Why (the one-paragraph pitch)
untangle already ships a Model Context Protocol server (`mcp_server.py`, FastMCP, **10 read-only tools**)
but only over **stdio** — an AI agent must install and run it locally. Competitors rated "best overall"
(Agent-Audit) expose a **remote streamable-HTTP MCP endpoint** that ChatGPT / claude.ai / Claude Code can
call with **no local install** — a big agent-native accessibility win (the Lethe "usability wins" lesson,
and dead-on-theme for an AI-agent buildathon). This feature adds that remote transport by **reusing the
exact same FastMCP server and its 10 tools** — we are only adding a transport, not new tools.

## 2. Hard constraints (Claude rejects the PR otherwise)
1. **REUSE the existing `mcp` FastMCP object and its 10 `@mcp.tool()` functions verbatim.** Do NOT
   reimplement, rename, or fork tools. The remote endpoint must serve the identical tool set as stdio.
2. **READ-ONLY.** Add no tool that writes, mutates, moves money, or takes a side-effect. untangle's MCP is
   read-only by design — that is a security *feature* (contrast: Agent-Audit's unauthenticated payment
   tool). Keep it that way.
3. **ADDITIVE.** The existing stdio mode (`untangle-mcp` → `mcp.run(transport="stdio")`) must keep working
   unchanged. Add the HTTP transport alongside it; do not replace it.
4. **Stateless / no auth for discovery** is acceptable (matches the reference pattern) *because every tool
   is read-only*. Do not add auth complexity; do not store per-client state.
5. stdlib-first + the existing `mcp` pin. The installed FastMCP already exposes `streamable_http_app()`
   (verified) — use it. Keep `mcp = ["mcp>=1.0,<2"]`; if a newer minor within `<2` is needed for the
   streamable-HTTP ASGI app, bump only the lower bound (stay `<2`) and say why in the PR.

## 3. What to build

### 3a. Mount the MCP HTTP app into the FastAPI web app (primary surface)
In `webapp/app.py`, mount the FastMCP streamable-HTTP ASGI app at **`/mcp`** so the SINGLE deployed app
serves both the web UI and the remote MCP endpoint (so once we deploy to Render, the remote MCP is live at
`https://<our-app>/mcp` for free):
- Import the existing server object: `from mcp_server import mcp`.
- Get its ASGI app: `mcp.streamable_http_app()` (FastMCP v1 provides this; `sse_app()` exists as a fallback
  if a client needs SSE — only add SSE at `/mcp/sse` if trivial, else skip).
- Mount it: `app.mount("/mcp", mcp.streamable_http_app())` (adjust to FastMCP's expected mount path/root;
  verify the handshake path resolves — the initialize handshake must return the server's `serverInfo`).
- **CORS:** allow cross-origin calls to `/mcp` (a hosted agent calls it from another origin). Add a narrow
  CORS policy for the `/mcp` mount only (GET/POST, the MCP content types), not the whole app.
- The FastMCP app may need its lifespan/session-manager started with the FastAPI lifespan — wire it into
  the existing app lifespan if required so the mounted app initializes cleanly (test the handshake to
  confirm).

### 3b. A standalone HTTP mode on the CLI (secondary, for local/other deploys)
Extend `mcp_server.py::main()` (and `[project.scripts] untangle-mcp`) to accept a transport flag:
- `untangle-mcp` (default) → stdio, unchanged.
- `untangle-mcp --http [--host 0.0.0.0] [--port 8081]` → `mcp.run(transport="streamable-http", ...)`.
Keep it a thin argument switch; do not duplicate tool code.

## 4. Tests (required)
- `tests/unit/test_mcp_http.py`:
  - Build the FastAPI app (or the mounted ASGI app) with a test client and perform the MCP **initialize**
    handshake against `/mcp`; assert it returns a valid `serverInfo` with the untangle server name.
  - Assert **tools/list** returns all 10 tool names (reconcile_files, list_unresolved_cash,
    explain_bank_credit, get_competing_explanations, suggest_next_evidence, export_proof_packet,
    verify_proof_packet, generate_close_certificate, export_journal_entries, investigate_variance).
  - Call one read-only tool (e.g. `reconcile_files` on `data/`) over HTTP and assert `ok: true` and the
    same headline shape the stdio path returns.
  - Assert the mount is READ-ONLY: there is no tool whose name/annotation implies a write/payment.
- Keep the existing `tests/unit/test_mcp_server.py` (stdio path) green — the tool set must be identical.
- CI: ensure `.github/workflows/ci.yml` still installs `[mcp]` so these run.

## 5. Docs (same PR — not optional; BUILD_PLAN §5)
- `README.md`: add a short "Remote MCP" note under the MCP/features section — that untangle exposes a
  public read-only MCP at `/mcp` callable from ChatGPT / claude.ai / Claude Code, with a one-line "add
  this URL" instruction (leave the actual URL as a placeholder until Render deploy).
- `docs/`: a short `docs/MCP.md` (or extend an existing MCP doc) with the streamable-HTTP endpoint, the
  tool list, and copy-paste connect instructions for claude.ai and ChatGPT. Note read-only + stateless.

## 6. Definition of done
`/mcp` streamable-HTTP endpoint mounted in the FastAPI app, serving the identical 10 read-only tools; MCP
initialize handshake returns untangle's `serverInfo`; tools/list returns all 10; a read-only tool call
works over HTTP; stdio mode unchanged; `untangle-mcp --http` works; CORS scoped to `/mcp`; tests green;
docs shipped; full suite + ruff clean. Once we deploy to Render, the remote MCP is live with zero extra
infra.

## 7. Reference pattern
Agent-Audit (github.com/Adarsh-Me/Agent-Audit) exposes exactly this shape: a public streamable-HTTP MCP at
`/mcp` whose handshake returns `{"serverInfo":{"name":...}}`, callable by hosted agents with no install.
Mirror the *shape* (public, stateless, read-only), not their code. Our advantage: every tool is read-only,
so we need none of their payment-tool auth hardening.

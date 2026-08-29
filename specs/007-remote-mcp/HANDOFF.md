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
   **SANDBOX (critical):** the tools take file *paths*. Over the PUBLIC HTTP surface an unauthenticated
   caller must NOT be able to open arbitrary server files. Add a path guard: when a sandbox flag
   (`UNTANGLE_MCP_SANDBOX`, set by the web app) is on, confine every caller path to the bundled demo-data
   dir (`UNTANGLE_MCP_DATA_DIR`, default `data/`) and reject anything outside it. **The remote MCP runs
   against the demo dataset; real user data goes through the web BYOD upload, not the public MCP.** Local
   stdio (trusted) stays unsandboxed. Also bound the one caller-supplied JSON arg (`verify_proof_packet`)
   with a size cap. A regression test must prove an out-of-sandbox path is rejected.
3. **ADDITIVE.** The existing stdio mode (`untangle-mcp` → `mcp.run(transport="stdio")`) must keep working
   unchanged. Add the HTTP transport alongside it; do not replace it.
4. **Stateless.** Set `mcp.settings.stateless_http = True` — no per-client session state accumulates in the
   container (correct for a public read-only endpoint; simpler for hosted clients). No auth for discovery
   is acceptable *because every tool is read-only AND sandboxed*.
5. **Pin `mcp>=1.8,<2`** — `streamable_http_app()`/streamable-HTTP transport needs SDK ≥1.8 (a `1.0–1.7`
   install would fail importing the server). Stay `<2` (FastMCP renamed in mcp 2.x).

## 3. What to build

### 3a. Mount the MCP HTTP app into the FastAPI web app (primary surface)
In `webapp/app.py`, mount the FastMCP streamable-HTTP ASGI app at **`/mcp`** so the SINGLE deployed app
serves both the web UI and the remote MCP endpoint (so once we deploy to Render, the remote MCP is live at
`https://<our-app>/mcp` for free):
- **FAIL-CLOSED sandbox, BEFORE importing the server**: `os.environ["UNTANGLE_MCP_SANDBOX"] = "1"` (force
  — NOT `setdefault`, which would leave an inherited `0` in place and start the public surface
  unsandboxed), and pin `UNTANGLE_MCP_DATA_DIR = os.path.abspath("data")`; then `from mcp_server import mcp`.
- **The demo dataset must exist in a fresh container.** `data/` is git/docker-ignored (regenerated from
  seed), so generate it at startup (`_ensure_demo_data()` in the lifespan runs the seeded generator if the
  files are absent). Otherwise every sandboxed tool call fails with no files to read.
- **Set `mcp.settings.streamable_http_path = "/"` BEFORE calling `streamable_http_app()`.** FastMCP's
  default is `/mcp`; mounting that under `/mcp` would expose the endpoint at `/mcp/mcp`. With the path set
  to `/`, the mount serves it at `/mcp/`. The handshake test must hit the FINAL public path (`/mcp/`).
- Create the ASGI app ONCE at import: `_mcp_asgi = mcp.streamable_http_app()`. This lazily constructs the
  FastMCP session manager, so `mcp.session_manager` becomes accessible (do NOT poke FastMCP private
  internals like `_session_manager`/`_mcp_server` to build it by hand).
- **Run the session manager in the FastAPI lifespan** (`async with mcp.session_manager.run(): yield`) —
  Starlette does not propagate a mounted app's lifespan, so the parent runs it. One app instance → one
  run; tests use a single module-scoped client so the lifespan is never re-entered.
- Mount it under CORS: `app.mount("/mcp", CORSMiddleware(app=_mcp_asgi, ...))`.
- **CORS must AGREE with the MCP origin allowlist** (else browsers get "preflight OK, then MCP rejects").
  Set `allow_origins` to `mcp.settings.transport_security.allowed_origins`, `allow_credentials=False`,
  `allow_methods=["GET","POST","DELETE","OPTIONS"]` (DELETE = session teardown), and allow the MCP headers
  (`content-type`, `accept`, `mcp-session-id`, `mcp-protocol-version`, `last-event-id`); expose
  `mcp-session-id`.
- Keep DNS-rebinding protection ON; `allowed_hosts`/`allowed_origins` are env-driven
  (`UNTANGLE_MCP_ALLOWED_HOSTS` / `_ORIGINS`) — the deploy MUST set the real host (§3c).

### 3c. Ship it — Dockerfile + deploy (without this the endpoint won't exist in production)
The Render image must `pip install -e ".[web,mcp]"` and `COPY mcp_server.py ./` (else `/mcp` is a no-op in
production). Auto-accept the deploy host: read `RENDER_EXTERNAL_HOSTNAME` (Render injects it) — but mind the
SHAPE: it is a **bare hostname**, so use it unchanged for `allowed_hosts` (host validation) and construct
`https://<hostname>` for `allowed_origins` (MCP compares the full browser `Origin`, scheme included).
`UNTANGLE_MCP_ALLOWED_HOSTS` remains the explicit override for custom domains / other platforms (document
it in `docs/DEPLOY.md`). The seed generator ships in the image, so `_ensure_demo_data()` can build `data/`
at startup — race-safe (lock + staging dir + atomic marker-last publish, mirroring `_ensure_sample`).

### 3d. Resource bounds (accepted posture + one deferred item)
The public endpoint is bounded by construction: tools are **sandboxed to the small seed-42 demo dataset**
(no arbitrary/large file parsing), `verify_proof_packet` **caps its input at 512 KB** (string AND dict),
and results are **`lru_cache`d** (repeat calls are cheap). Full per-IP **rate limiting + execution
timeouts + a concurrency cap** are deliberately deferred as post-deploy hardening (tracked task) — they
are not a demo blocker given the above, but MUST be added before treating this as real public production,
for BOTH the mounted and `--http` surfaces.

### 3b. A standalone HTTP mode on the CLI (secondary, for local/other deploys)
Extend `mcp_server.py::main()` (and `[project.scripts] untangle-mcp`) to accept a transport flag:
- `untangle-mcp` (default) → stdio, unchanged (unsandboxed — trusted local).
- `untangle-mcp --http [--host 0.0.0.0] [--port 8081]` → FORCE `os.environ["UNTANGLE_MCP_SANDBOX"]="1"`
  (it is a public bind), then `mcp.run(transport="streamable-http", ...)`.
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

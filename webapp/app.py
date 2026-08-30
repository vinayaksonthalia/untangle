"""untangle web app — landing, upload, live reconcile, dashboard, and a developer API.

Run:  .venv/bin/uvicorn webapp.app:app --port 8080   (or: python -m webapp.app)

Privacy by construction: uploaded files are written to a per-request temp directory, the
engine runs, and the directory is deleted immediately — nothing is persisted to disk or a
database, ever. Read-only toward money. The deterministic (--no-ai) path is the default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.cors import CORSMiddleware

from engine.certificate import issue_certificate, verify_certificate
from engine.ingest import InputError, load_bank
from engine.service import reconcile
from ui.dashboard import render as render_dashboard
from webapp.pages import landing_page, upload_page, verify_page

# The public /mcp endpoint must be sandboxed so an unauthenticated remote caller cannot open arbitrary
# server files. FAIL CLOSED: force the flag on (never `setdefault`, which would leave an inherited `0`
# in place) and pin the sandbox to the seed-42 demo dataset in data/, which is generated at startup
# (see `_ensure_demo_data` in the lifespan). Real user data goes through the web upload (BYOD), never
# the public MCP. Set BEFORE importing mcp_server — it reads these at import time.
os.environ["UNTANGLE_MCP_SANDBOX"] = "1"
os.environ.setdefault("UNTANGLE_MCP_DATA_DIR", os.path.abspath("data"))

try:
    from mcp_server import mcp

    # Create the streamable-HTTP ASGI app ONCE at import. This is what lazily constructs the FastMCP
    # session manager, so `mcp.session_manager` is accessible in the lifespan below (no poking of
    # FastMCP internals). Starlette does not propagate a mounted app's lifespan, so the parent app
    # runs the session manager itself.
    _mcp_asgi = mcp.streamable_http_app()
    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MCP_AVAILABLE = False


_DATA_LOCK = threading.Lock()


def _ensure_demo_data() -> None:
    """The sandboxed remote MCP reconciles the seed-42 demo dataset in `data/`. That directory is
    git/docker-ignored (regenerated from seed), so in a fresh container it is absent — generate it once
    at startup (the image ships the generator) so the MCP tools have files to operate on. In dev/CI the
    files already exist and this is a no-op.

    Generates into the SAME directory the MCP sandbox reads (`UNTANGLE_MCP_DATA_DIR`, set above to
    abspath(data/)) — never a hard-coded `data/` — so the generated files and the sandbox root can never
    diverge under an env override.

    Race-safe like `_ensure_sample`: serialise under a lock, generate into a private per-process staging
    dir, then publish with the marker (`bank_statement.csv`) moved LAST via atomic `os.replace` — so a
    concurrent lock-free reader (or a sibling worker process) that sees the marker is guaranteed to find
    every sibling file already in place, never a half-written dataset."""
    root = os.environ.get("UNTANGLE_MCP_DATA_DIR", os.path.abspath("data"))
    marker = os.path.join(root, "bank_statement.csv")
    if os.path.exists(marker):
        return
    from generator.generate import main as gen  # image includes generator/

    with _DATA_LOCK:
        if os.path.exists(marker):  # another thread finished while we waited
            return
        os.makedirs(root, exist_ok=True)
        staging = os.path.join(root, f".staging-{os.getpid()}")
        if os.path.exists(staging):
            shutil.rmtree(staging)
        try:
            gen(["--seed", "42", "--scale", "1.0", "--out", staging])
            for name in sorted(os.listdir(staging), key=lambda n: n == "bank_statement.csv"):
                os.replace(os.path.join(staging, name), os.path.join(root, name))
        finally:
            shutil.rmtree(staging, ignore_errors=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run the FastMCP session manager for the app's lifetime (stateless — no per-client state
    # accumulates). One app instance → one run; tests use a single module-scoped client, so this is
    # never re-entered.
    if _MCP_AVAILABLE:
        _ensure_demo_data()  # the sandbox points at data/ — make sure it exists in a fresh container
        async with mcp.session_manager.run():
            yield
    else:
        yield


_MAX_BYTES = 15 * 1024 * 1024  # 15 MB per file
app = FastAPI(title="untangle", docs_url="/api/docs", lifespan=lifespan)

# This is deliberately process-local: the public demo has no shared state store.  It protects a
# single instance from accidental refresh storms without pretending to be production auth/quotas.
_RATE_WINDOW_SECONDS = 60.0
_RATE_LIMIT = 20
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}
_MAX_VERIFY_BYTES = 512 * 1024
_RECONCILE_SLOTS = 2
_RECONCILE_TIMEOUT_SECONDS = 90.0
_RECONCILE_SEMAPHORE = threading.BoundedSemaphore(_RECONCILE_SLOTS)
_LOG = logging.getLogger("untangle.web")


@app.middleware("http")
async def safety_middleware(request: Request, call_next):
    global _RATE_BUCKETS
    started = time.perf_counter()
    # Never log caller-controlled request IDs: even a valid-looking value can contain newlines or
    # grow without bound.  The generated UUID is the only identifier used in responses/logs.
    request_id = uuid.uuid4().hex

    def finish(response):
        response.headers["x-request-id"] = request_id
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("content-security-policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'")
        _LOG.info("request_id=%s method=%s status=%s latency_ms=%.1f", request_id, request.method,
                  response.status_code, (time.perf_counter() - started) * 1000)
        return response
    if request.url.path in {"/reconcile", "/api/reconcile", "/api/verify"}:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _RATE_LOCK:
            if len(_RATE_BUCKETS) >= 4096 and client not in _RATE_BUCKETS:
                # Hard cap: evict the least-recently-seen bucket, even when all entries are active.
                oldest = min(_RATE_BUCKETS, key=lambda key: _RATE_BUCKETS[key][-1])
                del _RATE_BUCKETS[oldest]
            if len(_RATE_BUCKETS) > 4096:
                _RATE_BUCKETS = {key: values for key, values in _RATE_BUCKETS.items()
                                 if values and now - values[-1] < _RATE_WINDOW_SECONDS}
            recent = [t for t in _RATE_BUCKETS.get(client, []) if now - t < _RATE_WINDOW_SECONDS]
            if len(recent) >= _RATE_LIMIT:
                _RATE_BUCKETS[client] = recent
                response = JSONResponse({"detail": "Too many requests; try again shortly."}, status_code=429)
                response.headers["retry-after"] = "60"
                return finish(response)
            recent.append(now)
            _RATE_BUCKETS[client] = recent
    response = await call_next(request)
    # Keep the policy compatible with the deliberately self-contained demo pages (which use a
    # small inline script), while still preventing framing and unexpected base-URL changes.
    # The existing demo pages intentionally use tiny inline scripts/styles.  Keep this explicit and
    # scoped; a future production UI should replace unsafe-inline with nonces or hashes.
    return finish(response)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Small readiness endpoint; no filesystem, customer data, or internal paths are exposed."""
    return JSONResponse({"status": "ok", "version": os.environ.get("UNTANGLE_VERSION", "dev")})

if _MCP_AVAILABLE:
    # Align CORS with the MCP transport-security origin allowlist so a browser origin that clears the
    # preflight also clears the MCP handler (no "CORS says yes, MCP says no" mismatch). Read-only +
    # no credentials. Include DELETE (session teardown) and the MCP protocol headers.
    # The allowlist mixes EXACT origins (https://claude.ai) with port-wildcard entries (http://localhost:*)
    # that Starlette CORS matches only EXACTLY — so pass exact origins as allow_origins and translate any
    # ":*" port-wildcard into an allow_origin_regex (localhost/127.0.0.1 on any port).
    import re as _re

    _raw = list(getattr(mcp.settings.transport_security, "allowed_origins", None) or ["*"])
    _exact = [o for o in _raw if "*" not in o]
    _regex_parts = [
        _re.escape(o[:-2]) + r"(:\d+)?" for o in _raw if o.endswith(":*")
    ]  # "http://localhost:*" -> "http://localhost(:\d+)?"
    _origin_regex = "^(" + "|".join(_regex_parts) + ")$" if _regex_parts else None
    mcp_subapp = CORSMiddleware(
        app=_mcp_asgi,
        allow_origins=_exact,
        allow_origin_regex=_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "accept", "mcp-session-id", "mcp-protocol-version", "last-event-id"],
        expose_headers=["mcp-session-id"],
    )
    app.mount("/mcp", mcp_subapp)


# Dedicated demo dir — kept separate from data/ (the seed-42 single-month test/README baseline) so
# the multi-month demo can never overwrite the fixture the property tests pin to.
_SAMPLE = "sample_data"


def _months_by_key(bank_path: str) -> dict[str, str]:
    """Map each bank-credit line_key → its statement month ('YYYY-MM'), read straight from the
    source file via the same ingest the pipeline uses (so keys match the report exactly). Used only
    to filter the exception queue by month — it drives no metric."""
    try:
        return {ln.key: ln.value_date.strftime("%Y-%m") for ln in load_bank(bank_path)}
    except InputError:
        return {}


# The engine's own messages already name the file kind; we just strip the server path.
_SLOT_LABEL = {"bank_statement.csv": "file", "recon_report.json": "file",
               "order_ledger.csv": "file"}


def _kind_error(tmp: str, exc: Exception) -> HTTPException:
    """Turn any ingest/parse failure into a human message that never leaks server paths."""
    msg = str(exc)
    for fname, label in _SLOT_LABEL.items():
        msg = msg.replace(os.path.join(tmp, fname), f"your {label}")
    msg = msg.replace(tmp + os.sep, "").replace(tmp, "")
    if isinstance(exc, InputError):
        return HTTPException(422, f"Could not read your files: {msg}")
    if isinstance(exc, (UnicodeDecodeError, ValueError, KeyError)):
        return HTTPException(
            422,
            "One of your files doesn't look like the expected format. The bank statement and "
            "order ledger must be CSV text files, and the settlement report must be the JSON "
            "export from the Razorpay dashboard. Please re-export and try again.",
        )
    return HTTPException(500, "Something went wrong on our side processing the files. "
                              "Nothing was stored. Please try again.")


def _run_safely(tmp: str, bank: str, recon: str, ledger: str) -> dict:
    if not _RECONCILE_SEMAPHORE.acquire(timeout=0):
        raise HTTPException(503, "Reconciliation capacity is busy; please try again shortly.")
    try:
        return reconcile(bank, recon, ledger)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a kind, leak-free message
        raise _kind_error(tmp, exc) from exc
    finally:
        _RECONCILE_SEMAPHORE.release()


async def _run_safely_async(tmp: str, bank: str, recon: str, ledger: str) -> dict:
    """Run CPU-heavy reconciliation off the event loop.

    A timeout stops waiting for the worker, but cannot kill Python work already running in a
    thread; the semaphore still holds that slot until the worker actually returns.
    """
    # Read inputs before dispatching.  The worker owns its TemporaryDirectory, so an HTTP timeout
    # cannot delete files underneath a still-running thread when the request handler exits.
    inputs_list = []
    for path in (bank, recon, ledger):
        with open(path, "rb") as fh:
            inputs_list.append(fh.read())
    inputs = tuple(inputs_list)

    def worker() -> dict:
        with tempfile.TemporaryDirectory(prefix="untangle_worker_") as worker_tmp:
            paths = []
            for name, data in zip(("bank_statement.csv", "recon_report.json", "order_ledger.csv"), inputs, strict=True):
                path = os.path.join(worker_tmp, name)
                with open(path, "wb") as fh:
                    fh.write(data)
                paths.append(path)
            return _run_safely(worker_tmp, *paths)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(worker),
            timeout=_RECONCILE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(504, "Reconciliation timed out; no result was committed.") from exc


async def _save(tmp: str, name: str, up: UploadFile | None) -> str:
    if up is None:
        raise HTTPException(422, f"Missing file: {name}")
    data = await up.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, f"{name} is larger than 15 MB.")
    path = os.path.join(tmp, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


_SAMPLE_MARKER = "bank_statement.csv"
_SAMPLE_LOCK = threading.Lock()


def _ensure_sample() -> None:
    """Make sure the bundled sample data exists (generate it once if absent).

    Race-safe: sync endpoints run in a threadpool, so concurrent first hits could otherwise both
    generate into the same directory and let a reader see half-written inputs. We serialise
    generation under a lock, generate into a private staging dir, then publish the files with the
    marker (``bank_statement.csv``) moved LAST via an atomic ``os.replace`` — so a lock-free reader
    that sees the marker is guaranteed to find every sibling file already in place.
    """
    marker = os.path.join(_SAMPLE, _SAMPLE_MARKER)
    if os.path.exists(marker):
        return
    from generator.generate import main as gen  # web layer may use the generator

    with _SAMPLE_LOCK:
        if os.path.exists(marker):  # another thread finished while we waited
            return
        os.makedirs(_SAMPLE, exist_ok=True)
        staging = os.path.join(_SAMPLE, f".staging-{os.getpid()}")
        if os.path.exists(staging):
            shutil.rmtree(staging)
        try:
            # Multi-month sample (Apr–Jun 2026) so the dashboard's month filter has real content.
            # base-epoch 1775001600 = 2026-04-01 UTC; 91 days spans three calendar months.
            gen(["--seed", "42", "--scale", "0.15", "--base-epoch", "1775001600",
                 "--days", "91", "--out", staging])
            # publish non-marker files first, the marker last (True sorts after False)
            for name in sorted(os.listdir(staging), key=lambda n: n == _SAMPLE_MARKER):
                os.replace(os.path.join(staging, name), os.path.join(_SAMPLE, name))
        finally:
            shutil.rmtree(staging, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    return landing_page()


@app.get("/app", response_class=HTMLResponse)
def app_page() -> str:
    return upload_page()


@app.get("/try-sample", response_class=HTMLResponse)
def try_sample() -> str:
    _ensure_sample()
    bank = os.path.join(_SAMPLE, "bank_statement.csv")
    report = reconcile(
        bank,
        os.path.join(_SAMPLE, "recon_report.json"),
        os.path.join(_SAMPLE, "order_ledger.csv"),
    )
    return render_dashboard(report, _months_by_key(bank))


@app.post("/reconcile", response_class=HTMLResponse)
async def reconcile_upload(
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
) -> str:
    with tempfile.TemporaryDirectory(prefix="untangle_") as tmp:
        b = await _save(tmp, "bank_statement.csv", bank)
        r = await _save(tmp, "recon_report.json", recon)
        ln = await _save(tmp, "order_ledger.csv", ledger)
        report = await _run_safely_async(tmp, b, r, ln)
        return render_dashboard(report, _months_by_key(b))
    # temp dir (and every uploaded byte) is deleted here — nothing is kept.


@app.post("/api/reconcile")
async def api_reconcile(
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
) -> JSONResponse:
    """Developer API: three files in → the full report JSON out. Nothing stored."""
    with tempfile.TemporaryDirectory(prefix="untangle_api_") as tmp:
        b = await _save(tmp, "bank_statement.csv", bank)
        r = await _save(tmp, "recon_report.json", recon)
        ln = await _save(tmp, "order_ledger.csv", ledger)
        report = await _run_safely_async(tmp, b, r, ln)
        return JSONResponse(report)


@app.get("/api/certificate/sample")
def api_certificate_sample() -> JSONResponse:
    """The signed (or hash-only) period close certificate for the bundled sample run — a portable,
    independently-verifiable artifact. Nothing stored."""
    _ensure_sample()
    report = reconcile(
        os.path.join(_SAMPLE, "bank_statement.csv"),
        os.path.join(_SAMPLE, "recon_report.json"),
        os.path.join(_SAMPLE, "order_ledger.csv"),
    )
    return JSONResponse(issue_certificate(report))


@app.get("/api/journal/sample.tally.xml")
def api_journal_tally() -> Response:
    """The reconciled Razorpay slice as a Tally Prime voucher-import XML — download and import via
    Gateway of Tally > Import > Vouchers. Balanced to the paise. Nothing stored."""
    from engine.journal import journal_json_to_tally_xml
    _ensure_sample()
    report = reconcile(
        os.path.join(_SAMPLE, "bank_statement.csv"),
        os.path.join(_SAMPLE, "recon_report.json"),
        os.path.join(_SAMPLE, "order_ledger.csv"),
    )
    xml = journal_json_to_tally_xml(report.get("journal") or [], company="Your Company Name")
    return Response(
        content=xml, media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="untangle_tally_vouchers.xml"'},
    )


@app.post("/api/verify")
async def api_verify(request: Request) -> JSONResponse:
    """Independently verify a close-certificate envelope: re-derive its SHA-256 content hash and, when
    signed, check the ECDSA signature. No trust in this server required — a tampered field breaks the
    hash; a forged certificate fails the signature."""
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > _MAX_VERIFY_BYTES):
        raise HTTPException(413, "Certificate payload is larger than 512 KB.")
    try:
        raw = await request.body()
        if len(raw) > _MAX_VERIFY_BYTES:
            raise HTTPException(413, "Certificate payload is larger than 512 KB.")
        payload = json.loads(raw)
    except HTTPException:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Certificate payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "Certificate payload must be a JSON object.")
    return JSONResponse(verify_certificate(payload))


@app.get("/verify", response_class=HTMLResponse)
def verify() -> str:
    return verify_page()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)

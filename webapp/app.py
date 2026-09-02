"""untangle web app — landing, upload, live reconcile, dashboard, and a developer API.

Run:  .venv/bin/uvicorn webapp.app:app --port 8080   (or: python -m webapp.app)

Privacy by construction: admitted uploads are converted to bounded immutable byte snapshots and
are never persisted to an application database. Read-only toward money. The deterministic
(--no-ai) path is the default.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import pathlib
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from engine.certificate import issue_certificate, verify_certificate
from engine.ingest import InputError, load_bank, load_bank_bytes
from engine.service import reconcile, reconcile_bytes
from ui.dashboard import render as render_dashboard
from webapp.pages import (
    dashboard_page,
    investigate_page,
    landing_page,
    upload_page,
    verify_page,
)

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

# Serve the landing page's committed, self-hosted assets (compiled CSS + woff2 fonts).
# Mounted under a dedicated /static prefix that never overlaps an app route or the /mcp
# sub-app, so route resolution is unchanged. Everything here is first-party — the hardened
# CSP (default-src 'self') requires it, since external stylesheet/font hosts are blocked.
mimetypes.add_type("font/woff2", ".woff2")
_STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
if not _STATIC_DIR.is_dir():  # fail loudly at import rather than 404 silently in prod
    raise RuntimeError(f"static assets directory missing: {_STATIC_DIR}")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

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

# Aggregate request-body ceiling for the upload endpoints: three 15 MB files plus multipart framing.
# Enforced by byte-counting the ASGI stream (below), so a chunked / Content-Length-less request
# cannot spool an unbounded body before the per-file checks in _save run.
_MAX_AGGREGATE_BYTES = 3 * _MAX_BYTES + 1024 * 1024
_BODY_LIMITS = {
    "/reconcile": _MAX_AGGREGATE_BYTES,
    "/api/reconcile": _MAX_AGGREGATE_BYTES,
    "/api/presentation": _MAX_AGGREGATE_BYTES,
    "/api/verify": _MAX_VERIFY_BYTES,
}
_BODY_INGEST_TIMEOUT_SECONDS = 30.0


class BodySizeLimitMiddleware:
    """Cap request-body size by reading bytes off the ASGI stream BEFORE the app parses them.

    A ``Content-Length`` over the ceiling is rejected up front. For requests without one (chunked /
    streamed), the body is buffered a chunk at a time only up to the ceiling; the instant the tally
    exceeds it, we return 413 and never invoke the app — so multipart parsing can neither consume
    nor spool more than the configured aggregate limit, regardless of transfer framing. Legitimate
    under-limit bodies are replayed to the app unchanged, so memory is bounded to the ceiling.

    Buffering (rather than a wrapped-receive that raises) is deliberate: an exception raised from
    ``receive`` while the inner ``BaseHTTPMiddleware`` is streaming the body surfaces as a 500, not
    a 413. Reading ahead and short-circuiting keeps the rejection clean.
    """

    def __init__(self, app, *, limits: dict[str, int]) -> None:
        self.app = app
        self.limits = limits

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in self.limits:
            await self.app(scope, receive, send)
            return
        max_bytes = self.limits[scope["path"]]
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            declared = content_length.decode("latin-1").strip()
            if not declared.isdigit() or int(declared) > max_bytes:
                await self._reject(send)
                return

        buffered: list[dict] = []
        received = 0
        deadline = time.monotonic() + _BODY_INGEST_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._reject_timeout(send)
                return
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                await self._reject_timeout(send)
                return
            if message["type"] != "http.request":
                buffered.append(message)  # e.g. http.disconnect — hand it through unchanged
                break
            received += len(message.get("body", b""))
            if received > max_bytes:
                await self._reject(send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        replay = iter(buffered)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return await receive()  # any messages beyond the buffered body (e.g. disconnect)

        await self.app(scope, replay_receive, send)

    async def _reject(self, send) -> None:
        # Stamp the baseline security headers and a request id directly, so the 413 carries them even
        # if this layer's ordering changes; safety_middleware also applies them via setdefault.
        body = b'{"detail":"Request body is too large."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", uuid.uuid4().hex.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _reject_timeout(self, send) -> None:
        body = b'{"detail":"Request body upload timed out."}'
        await send(
            {
                "type": "http.response.start",
                "status": 408,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                    (b"x-request-id", uuid.uuid4().hex.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# Registered BEFORE safety_middleware so safety_middleware ends up the OUTERMOST layer: the per-IP
# rate-limit / admission decision must run before this middleware consumes (buffers) the body, so an
# already-limited client is turned away cheaply instead of forcing full request ingestion each time.
# safety_middleware never reads the body, so this middleware still sees the raw byte stream.
app.add_middleware(BodySizeLimitMiddleware, limits=_BODY_LIMITS)


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
        response.headers.setdefault(
            "content-security-policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'",
        )
        _LOG.info(
            "request_id=%s method=%s status=%s latency_ms=%.1f",
            request_id,
            request.method,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    if request.url.path in {"/reconcile", "/api/reconcile", "/api/presentation", "/api/verify"}:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _RATE_LOCK:
            if len(_RATE_BUCKETS) >= 4096 and client not in _RATE_BUCKETS:
                # Hard cap: evict the least-recently-seen bucket, even when all entries are active.
                oldest = min(_RATE_BUCKETS, key=lambda key: _RATE_BUCKETS[key][-1])
                del _RATE_BUCKETS[oldest]
            if len(_RATE_BUCKETS) > 4096:
                _RATE_BUCKETS = {
                    key: values
                    for key, values in _RATE_BUCKETS.items()
                    if values and now - values[-1] < _RATE_WINDOW_SECONDS
                }
            recent = [t for t in _RATE_BUCKETS.get(client, []) if now - t < _RATE_WINDOW_SECONDS]
            if len(recent) >= _RATE_LIMIT:
                _RATE_BUCKETS[client] = recent
                response = JSONResponse(
                    {"detail": "Too many requests; try again shortly."}, status_code=429
                )
                response.headers["retry-after"] = "60"
                return finish(response)
            recent.append(now)
            _RATE_BUCKETS[client] = recent
    slot = None
    if request.url.path in {"/reconcile", "/api/reconcile", "/api/presentation"}:
        # Validate the cheap declared length before admission.  Otherwise an oversized request can
        # occupy a worker slot until BodySizeLimitMiddleware rejects it with 413.
        declared_length = request.headers.get("content-length")
        limit = _BODY_LIMITS[request.url.path]
        if declared_length is not None:
            try:
                declared = int(declared_length)
            except ValueError:
                declared = -1
            if declared < 0 or declared > limit:
                return finish(JSONResponse({"detail": "Request body is too large."}, status_code=413))
        # This middleware is outermost, so admission happens before BodySizeLimitMiddleware reads
        # the body and before FastAPI parses/spools multipart UploadFile values.
        if not _RECONCILE_SEMAPHORE.acquire(timeout=0):
            return finish(
                JSONResponse(
                    {"detail": "Reconciliation capacity is busy; please try again shortly."},
                    status_code=503,
                )
            )
        slot = _ReconciliationSlot()
        request.state.reconciliation_slot = slot
    try:
        response = await call_next(request)
        # Keep the policy compatible with the deliberately self-contained demo pages.
        return finish(response)
    finally:
        if slot is not None:
            slot.release_if_held()


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
        allow_headers=[
            "content-type",
            "accept",
            "mcp-session-id",
            "mcp-protocol-version",
            "last-event-id",
        ],
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
_SLOT_LABEL = {
    "bank_statement.csv": "file",
    "recon_report.json": "file",
    "order_ledger.csv": "file",
}


def _kind_error(exc: Exception, *tmp_roots: str) -> HTTPException:
    """Turn any ingest/parse/IO failure into a human message that never leaks server paths.

    Legacy path-based callers may supply temporary roots to scrub. Upload endpoints use immutable
    byte snapshots and therefore have no application-owned upload path to expose.
    """
    msg = str(exc)
    for root in tmp_roots:
        for fname, label in _SLOT_LABEL.items():
            msg = msg.replace(os.path.join(root, fname), f"your {label}")
        msg = msg.replace(root + os.sep, "").replace(root, "")
    if isinstance(exc, InputError):
        return HTTPException(422, f"Could not read your files: {msg}")
    if isinstance(exc, (UnicodeDecodeError, ValueError, KeyError)):
        return HTTPException(
            422,
            "One of your files doesn't look like the expected format. The bank statement and "
            "order ledger must be CSV text files, and the settlement report must be the JSON "
            "export from the Razorpay dashboard. Please re-export and try again.",
        )
    return HTTPException(
        500,
        "Something went wrong on our side processing the files. "
        "Nothing was stored. Please try again.",
    )


class _ReconciliationSlot:
    """Manages atomic ownership and release of a reconciliation concurrency slot."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "held"  # "held" -> "running" (worker owns) | "freed" (handler freed)

    def mark_running(self) -> bool:
        """Called inside worker thread. Returns True if worker successfully took ownership."""
        with self.lock:
            if self.state != "held":
                return False
            self.state = "running"
            return True

    def release_if_held(self) -> bool:
        """Called by async handler on error/timeout/cancellation before worker takes ownership."""
        with self.lock:
            if self.state == "held":
                self.state = "freed"
                _RECONCILE_SEMAPHORE.release()
                return True
            return False

    def release_from_worker(self) -> None:
        """Called in worker finally block."""
        with self.lock:
            if self.state != "running":
                raise RuntimeError(f"invalid reconciliation slot release from state {self.state!r}")
            self.state = "freed"
            _RECONCILE_SEMAPHORE.release()


async def _run_safely_bytes_async(
    bank_bytes: bytes,
    recon_bytes: bytes,
    ledger_bytes: bytes,
    *,
    slot: _ReconciliationSlot,
) -> dict:
    """Run the engine on request-owned immutable snapshots under an already-admitted slot."""

    def worker() -> dict:
        if not slot.mark_running():
            return {}
        try:
            try:
                return reconcile_bytes(bank_bytes, recon_bytes, ledger_bytes)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 — sanitize every parse/engine failure
                raise _kind_error(exc) from exc
        finally:
            slot.release_from_worker()

    try:
        return await asyncio.wait_for(asyncio.to_thread(worker), timeout=_RECONCILE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        slot.release_if_held()
        raise HTTPException(504, "Reconciliation timed out; no result was committed.") from exc
    except asyncio.CancelledError:
        slot.release_if_held()
        raise


async def _run_safely_async(
    tmp: str,
    bank: str,
    recon: str,
    ledger: str,
    *,
    slot: _ReconciliationSlot | None = None,
) -> dict:
    """Run reconciliation off the event loop, under the concurrency bound.

    Admission FIRST: reserve a reconciliation slot before any large read or copy, so an
    over-capacity request is turned away (503) cheaply instead of buffering ~45 MB and stalling the
    event loop on synchronous I/O. Every file read/copy/parse then runs in the worker THREAD, not on
    the loop, and every failure there is mapped to a leak-free HTTP error.

    Slot ownership is handed off atomically under ``_ReconciliationSlot``: exactly one party releases the slot.
    A *running* worker keeps its slot until it finishes (so a timed-out/cancelled handler cannot free
    a slot still in use, and the worker owns immutable input bytes so the handler's tmp cleanup can't
    race it); but if cancellation kills the offload *before* the worker starts, the handler frees the
    slot so it can never leak.
    """
    if slot is None:
        if not _RECONCILE_SEMAPHORE.acquire(timeout=0):
            raise HTTPException(503, "Reconciliation capacity is busy; please try again shortly.")
        slot = _ReconciliationSlot()

    def worker() -> dict:
        if not slot.mark_running():
            return {}  # handler already freed the slot after cancellation; do not run or release
        try:
            try:
                inputs = []
                for path in (bank, recon, ledger):
                    with open(path, "rb") as fh:
                        inputs.append(fh.read())
                return reconcile_bytes(*inputs)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 — sanitize every read/parse failure
                raise _kind_error(exc, tmp) from exc
        finally:
            slot.release_from_worker()  # this worker owns the slot; release exactly once

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(worker),
            timeout=_RECONCILE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        slot.release_if_held()
        raise HTTPException(504, "Reconciliation timed out; no result was committed.") from exc
    except asyncio.CancelledError:
        slot.release_if_held()
        raise


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


async def _read_upload(name: str, up: UploadFile | None) -> bytes:
    """Read one admitted upload into a bounded immutable snapshot."""
    if up is None:
        raise HTTPException(422, f"Missing file: {name}")
    data = await up.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, f"{name} is larger than 15 MB.")
    return bytes(data)


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
            gen(
                [
                    "--seed",
                    "42",
                    "--scale",
                    "0.15",
                    "--base-epoch",
                    "1775001600",
                    "--days",
                    "91",
                    "--out",
                    staging,
                ]
            )
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
    request: Request,
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
) -> str:
    slot = request.state.reconciliation_slot
    b = await _read_upload("bank_statement.csv", bank)
    r = await _read_upload("recon_report.json", recon)
    ln = await _read_upload("order_ledger.csv", ledger)
    report = await _run_safely_bytes_async(b, r, ln, slot=slot)
    months = {line.key: line.value_date.strftime("%Y-%m") for line in load_bank_bytes(b)}
    return render_dashboard(report, months)


@app.post("/api/reconcile")
async def api_reconcile(
    request: Request,
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
) -> JSONResponse:
    """Developer API: three files in → the full report JSON out. Nothing stored."""
    slot = request.state.reconciliation_slot
    b = await _read_upload("bank_statement.csv", bank)
    r = await _read_upload("recon_report.json", recon)
    ln = await _read_upload("order_ledger.csv", ledger)
    report = await _run_safely_bytes_async(b, r, ln, slot=slot)
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
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="untangle_tally_vouchers.xml"'},
    )


@app.post("/api/verify")
async def api_verify(request: Request) -> JSONResponse:
    """Verify a certificate envelope and any attached report binding without raising."""
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


_SAMPLE_FILES = ("bank_statement.csv", "recon_report.json", "order_ledger.csv")
_SAMPLE_CACHE_LOCK = threading.Lock()  # single-flight: coalesce concurrent cache misses


def _sample_fingerprint() -> tuple:
    """Identity of everything the cached result depends on: the sample inputs (path, size,
    mtime) AND the signing-key context (issue_certificate signs with $UNTANGLE_SIGNING_KEY).

    Keying on the signing key too means rotating/removing it busts the cache, so the endpoint
    can never serve a certificate the current verification key would reject. Caller must
    _ensure_sample() first. The key value itself is hashed, never stored in the key.
    """
    files = tuple(
        (name, (st := os.stat(os.path.join(_SAMPLE, name))).st_size, st.st_mtime_ns)
        for name in _SAMPLE_FILES
    )
    pem = os.environ.get("UNTANGLE_SIGNING_KEY", "")  # engine.certificate._SIGNING_KEY_ENV
    key_id = hashlib.sha256(pem.encode()).hexdigest()[:16] if pem else "unsigned"
    return files + (("signing_key", key_id),)


@lru_cache(maxsize=2)
def _sample_report_and_cert(fingerprint: tuple):
    """Reconcile the bundled sample once PER INPUT VERSION and cache the report + certificate.

    Keyed on the sample files' identity (`fingerprint`), NOT on process history: if the sample
    artifacts change (regenerated → new size/mtime), the key changes and we recompute, so a stale
    financial result can never be served. The expensive reconciliation + certificate build must not
    run on every request either — GET /api/presentation/sample is hit on every dashboard load and
    is exempt from rate-limit/capacity admission, so re-running the full pipeline per request would
    be a cheap unauthenticated DoS. Pagination stays per-request (cheap).
    """
    report = reconcile(
        os.path.join(_SAMPLE, "bank_statement.csv"),
        os.path.join(_SAMPLE, "recon_report.json"),
        os.path.join(_SAMPLE, "order_ledger.csv"),
    )
    return report, issue_certificate(report)


@app.get("/api/presentation/sample")
def api_presentation_sample(limit: int = 100, offset: int = 0) -> JSONResponse:
    """Presentation contract for the bundled sample run — safe, read-only UI data. Nothing stored."""
    from webapp.presentation import PresentationSchemaError, build_presentation_payload

    _ensure_sample()
    # expensive part cached per input version (fingerprint); only paginate per request.
    # The lock is single-flight: on a cache miss only one thread reconciles while the rest
    # wait for its cached result, so a cold-start / post-update burst can't saturate the
    # worker pool with duplicate reconciliations (this GET bypasses capacity admission).
    with _SAMPLE_CACHE_LOCK:
        report, cert = _sample_report_and_cert(_sample_fingerprint())
    try:
        presentation = build_presentation_payload(report, certificate=cert, limit=limit, offset=offset)
    except PresentationSchemaError as exc:
        raise HTTPException(422, str(exc)) from exc
    return JSONResponse(presentation)


@app.post("/api/presentation")
async def api_presentation(
    request: Request,
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
    limit: int = 100,
    offset: int = 0,
) -> JSONResponse:
    """Presentation contract for uploaded statements — safe, read-only UI data. Nothing stored."""
    from webapp.presentation import PresentationSchemaError, build_presentation_payload

    slot = request.state.reconciliation_slot
    b = await _read_upload("bank_statement.csv", bank)
    r = await _read_upload("recon_report.json", recon)
    ln = await _read_upload("order_ledger.csv", ledger)
    report = await _run_safely_bytes_async(b, r, ln, slot=slot)
    cert = issue_certificate(report)
    try:
        presentation = build_presentation_payload(report, certificate=cert, limit=limit, offset=offset)
    except PresentationSchemaError as exc:
        raise HTTPException(422, str(exc)) from exc
    return JSONResponse(presentation)


_SEALED_CACHE: dict | None = None
_SEALED_LOCK = threading.Lock()


def _get_cached_sealed_presentation() -> dict:
    global _SEALED_CACHE
    if _SEALED_CACHE is not None:
        return _SEALED_CACHE
    with _SEALED_LOCK:
        if _SEALED_CACHE is not None:
            return _SEALED_CACHE
        from webapp.presentation import build_sealed_evaluation_presentation

        _SEALED_CACHE = build_sealed_evaluation_presentation(allow_compute_if_absent=True)
        return _SEALED_CACHE


@app.get("/api/evaluation/sealed")
def api_evaluation_sealed() -> JSONResponse:
    """Server-authenticated sealed holdout benchmark presentation (read-only, E3 protocol)."""
    try:
        eval_payload = _get_cached_sealed_presentation()
    except Exception as exc:
        _LOG.warning("Sealed evaluation benchmark unavailable: %s", exc)
        return JSONResponse(
            {"status": "unavailable", "detail": "Sealed evaluation benchmark unavailable."},
            status_code=503,
        )
    return JSONResponse(eval_payload)


_INVESTIGATIONS_CACHE: dict | None = None
_INVESTIGATIONS_LOCK = threading.Lock()

# Root-cause labels + the accounting family each belongs to. Kept server-side so the UI renders
# a human label and a colour family without re-deriving finance semantics in the browser.
_ROOT_CAUSE_LABELS = {
    "mdr_fee_drift": "MDR fee drift",
    "cross_cycle_refund_lag": "Cross-cycle refund lag",
    "on_hold_release": "On-hold release",
    "dispute_deduction": "Dispute deduction",
    "partial_capture": "Partial capture",
    "rolling_reserve": "Rolling reserve",
    "bank_charge_or_rounding": "Bank charge / rounding",
    "unexplained": "Unexplained",
}


def _build_investigations_payload() -> dict:
    """Run the deterministic investigation benchmark once and shape a read-only UI payload.

    Uses the seed-42 investigation benchmark (one settlement per root cause + one genuinely
    ambiguous control that the engine abstains on). Everything here is derived, synthetic and
    safe to expose; nothing is persisted. The heavy generate+reconcile runs once and is cached.
    """
    import tempfile

    from generator.config import Config
    from generator.investigation_cases import write_investigation_benchmark

    work = tempfile.mkdtemp(prefix="untangle_inv_")
    try:
        write_investigation_benchmark(work, Config())
        base = os.path.join(work, "investigation")
        with open(os.path.join(base, "bank_statement.csv"), "rb") as fh:
            bank = fh.read()
        with open(os.path.join(base, "recon_report.json"), "rb") as fh:
            recon = fh.read()
        with open(os.path.join(base, "order_ledger.csv"), "rb") as fh:
            ledger = fh.read()
        report = reconcile_bytes(bank, recon, ledger)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    cases = []
    for inv in report.get("investigations") or []:
        rc = inv.get("root_cause", "unexplained")
        cases.append(
            {
                "line_key": inv.get("line_key"),
                "root_cause": rc,
                "root_cause_label": _ROOT_CAUSE_LABELS.get(rc, rc),
                "resolved": rc != "unexplained",
                "confidence": inv.get("confidence", 0.0),
                "variance_paise": inv.get("variance_paise", 0),
                "variance_inr": inv.get("variance_inr", "0.00"),
                "reasoning_trace": inv.get("reasoning_trace") or [],
                "candidates_tried": inv.get("candidates_tried") or [],
                "corrective_entry": inv.get("corrective_entry"),
            }
        )
    resolved = sum(1 for c in cases if c["resolved"])
    return {
        "run_identity": report.get("run_identity") or {},
        "summary": {
            "total": len(cases),
            "resolved": resolved,
            "abstained": len(cases) - resolved,
        },
        "cases": cases,
    }


def _get_cached_investigations() -> dict:
    global _INVESTIGATIONS_CACHE
    if _INVESTIGATIONS_CACHE is not None:
        return _INVESTIGATIONS_CACHE
    with _INVESTIGATIONS_LOCK:
        if _INVESTIGATIONS_CACHE is not None:
            return _INVESTIGATIONS_CACHE
        _INVESTIGATIONS_CACHE = _build_investigations_payload()
        return _INVESTIGATIONS_CACHE


@app.get("/api/investigations/sample")
def api_investigations_sample() -> JSONResponse:
    """Read-only root-cause investigations for the bundled benchmark. Deterministic; nothing stored."""
    try:
        payload = _get_cached_investigations()
    except Exception as exc:  # pragma: no cover - defensive; benchmark is deterministic
        _LOG.warning("Investigations benchmark unavailable: %s", exc)
        return JSONResponse(
            {"status": "unavailable", "detail": "Investigations benchmark unavailable."},
            status_code=503,
        )
    return JSONResponse(payload)


@app.get("/investigate", response_class=HTMLResponse)
def investigate() -> str:
    return investigate_page()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return dashboard_page()


@app.get("/verify", response_class=HTMLResponse)
def verify() -> str:
    return verify_page()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)

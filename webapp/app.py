"""untangle web app — landing, upload, live reconcile, dashboard, and a developer API.

Run:  .venv/bin/uvicorn webapp.app:app --port 8080   (or: python -m webapp.app)

Privacy by construction: uploaded files are written to a per-request temp directory, the
engine runs, and the directory is deleted immediately — nothing is persisted to disk or a
database, ever. Read-only toward money. The deterministic (--no-ai) path is the default.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from engine.certificate import issue_certificate, verify_certificate
from engine.ingest import InputError, load_bank
from engine.service import reconcile
from ui.dashboard import render as render_dashboard
from webapp.pages import landing_page, upload_page, verify_page

app = FastAPI(title="untangle", docs_url="/api/docs")

_MAX_BYTES = 15 * 1024 * 1024  # 15 MB per file — a month of settlements is far smaller
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
    try:
        return reconcile(bank, recon, ledger)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a kind, leak-free message
        raise _kind_error(tmp, exc) from exc


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
        report = _run_safely(tmp, b, r, ln)
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
        report = _run_safely(tmp, b, r, ln)
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


@app.post("/api/verify")
async def api_verify(payload: dict) -> JSONResponse:
    """Independently verify a close-certificate envelope: re-derive its SHA-256 content hash and, when
    signed, check the ECDSA signature. No trust in this server required — a tampered field breaks the
    hash; a forged certificate fails the signature."""
    return JSONResponse(verify_certificate(payload))


@app.get("/verify", response_class=HTMLResponse)
def verify() -> str:
    return verify_page()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)

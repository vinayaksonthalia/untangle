"""untangle web app — landing, upload, live reconcile, dashboard, and a developer API.

Run:  .venv/bin/uvicorn webapp.app:app --port 8080   (or: python -m webapp.app)

Privacy by construction: uploaded files are written to a per-request temp directory, the
engine runs, and the directory is deleted immediately — nothing is persisted to disk or a
database, ever. Read-only toward money. The deterministic (--no-ai) path is the default.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from engine.ingest import InputError
from engine.service import reconcile
from ui.dashboard import render as render_dashboard
from webapp.pages import landing_page, upload_page

app = FastAPI(title="untangle", docs_url="/api/docs")

_MAX_BYTES = 15 * 1024 * 1024  # 15 MB per file — a month of settlements is far smaller
_SAMPLE = "data"


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


def _ensure_sample() -> None:
    """Make sure bundled sample data exists (generate it once if absent)."""
    if os.path.exists(os.path.join(_SAMPLE, "bank_statement.csv")):
        return
    from generator.generate import main as gen  # web layer may use the generator
    gen(["--seed", "42", "--scale", "0.4", "--out", _SAMPLE])


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    return landing_page()


@app.get("/app", response_class=HTMLResponse)
def app_page() -> str:
    return upload_page()


@app.get("/try-sample", response_class=HTMLResponse)
def try_sample() -> str:
    _ensure_sample()
    report = reconcile(
        os.path.join(_SAMPLE, "bank_statement.csv"),
        os.path.join(_SAMPLE, "recon_report.json"),
        os.path.join(_SAMPLE, "order_ledger.csv"),
    )
    return render_dashboard(report)


@app.post("/reconcile", response_class=HTMLResponse)
async def reconcile_upload(
    bank: UploadFile = File(...),
    recon: UploadFile = File(...),
    ledger: UploadFile = File(...),
) -> str:
    with tempfile.TemporaryDirectory(prefix="untangle_") as tmp:
        b = await _save(tmp, "bank_statement.csv", bank)
        r = await _save(tmp, "recon_report.json", recon)
        l = await _save(tmp, "order_ledger.csv", ledger)
        report = _run_safely(tmp, b, r, l)
        return render_dashboard(report)
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
        l = await _save(tmp, "order_ledger.csv", ledger)
        report = _run_safely(tmp, b, r, l)
        return JSONResponse(report)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)

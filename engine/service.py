"""Reusable reconciliation entry point shared by the CLI and the web app.

Runs the full pipeline over three file paths and returns the report as a plain dict.
Read-only toward money; deterministic on the --no-ai path. The web layer writes uploads
to a temp dir, calls this, then deletes them — nothing is persisted.
"""

from __future__ import annotations

from engine.attribute import attribute_all
from engine.cli import build_report
from engine.config import build_config
from engine.evidence import ReconIndex
from engine.ingest import InputError, load_bank_bytes, load_ledger_bytes, load_recon_bytes
from engine.llm.client import LLMClient
from engine.llm.narrate import resolve_unknowns

MAX_INPUT_BYTES = 15 * 1024 * 1024
_SNAPSHOT_CHUNK_BYTES = 64 * 1024


def reconcile_bytes(
    bank_bytes: bytes,
    recon_bytes: bytes,
    ledger_bytes: bytes,
    *,
    no_ai: bool = True,
    provider: str | None = None,
    model: str | None = None,
    threshold: float | None = None,
    seed: int = 42,
    global_solver: bool = False,
) -> dict:
    """Reconcile one immutable in-memory snapshot of the three inputs."""
    lines = load_bank_bytes(bank_bytes)
    recon_rows = load_recon_bytes(recon_bytes)
    order_ledger = load_ledger_bytes(ledger_bytes)
    return _reconcile_loaded(
        lines,
        recon_rows,
        order_ledger,
        no_ai=no_ai,
        provider=provider,
        model=model,
        threshold=threshold,
        seed=seed,
        global_solver=global_solver,
    )


def read_input_snapshot(path: str, *, label: str, option: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            chunks: list[bytes] = []
            total = 0
            while chunk := fh.read(min(_SNAPSHOT_CHUNK_BYTES, MAX_INPUT_BYTES + 1 - total)):
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise InputError(
                        f"{label} is too large ({total:,} bytes read); maximum supported size is "
                        f"{MAX_INPUT_BYTES:,} bytes."
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    except FileNotFoundError as exc:
        raise InputError(f"{label} not found: {path}. Check the {option} path.") from exc


def reconcile(
    bank_path: str,
    recon_path: str,
    ledger_path: str,
    *,
    no_ai: bool = True,
    provider: str | None = None,
    model: str | None = None,
    threshold: float | None = None,
    seed: int = 42,
    global_solver: bool = False,
) -> dict:
    """Read every input once, then reconcile the exact immutable byte snapshot."""
    snapshots = (
        read_input_snapshot(bank_path, label="Bank statement", option="--bank"),
        read_input_snapshot(recon_path, label="Recon report", option="--recon"),
        read_input_snapshot(ledger_path, label="Order ledger", option="--ledger"),
    )
    return reconcile_bytes(
        *snapshots,
        no_ai=no_ai,
        provider=provider,
        model=model,
        threshold=threshold,
        seed=seed,
        global_solver=global_solver,
    )


def _reconcile_loaded(
    lines,
    recon_rows,
    order_ledger,
    *,
    no_ai: bool = True,
    provider: str | None = None,
    model: str | None = None,
    threshold: float | None = None,
    seed: int = 42,
    global_solver: bool = False,
) -> dict:
    """Attribute → reconcile → fee-GST → exceptions from already parsed snapshots."""
    cfg = build_config(
        no_ai=no_ai,
        provider=provider,
        model=model,
        threshold=threshold,
        seed=seed,
        global_solver=global_solver,
    )
    index = ReconIndex(recon_rows)
    solver_out: dict = {}
    attributions = attribute_all(
        lines,
        index,
        cfg.threshold,
        global_solver=cfg.global_solver,
        solver_result_out=solver_out if cfg.global_solver else None,
        audit_challenger=True,  # evidence courtroom: attach proof margin + rejected explanation (display-only)
    )
    if cfg.use_ai:
        client = LLMClient(enabled=True, provider=cfg.provider, model=cfg.model, api_key=cfg.api_key)
        attributions = resolve_unknowns(attributions, {ln.key: ln for ln in lines}, index, client)
    report, _ledger = build_report(
        cfg,
        lines,
        recon_rows,
        index,
        attributions,
        order_ledger,
        global_solver=cfg.global_solver,
        solver_result=solver_out.get("solver_result"),
    )
    return report.to_dict()

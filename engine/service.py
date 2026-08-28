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
from engine.ingest import load_bank, load_ledger, load_recon
from engine.llm.client import LLMClient
from engine.llm.narrate import resolve_unknowns


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
    """Ingest → attribute → reconcile → fee-GST → exceptions; return report.to_dict()."""
    cfg = build_config(
        no_ai=no_ai,
        provider=provider,
        model=model,
        threshold=threshold,
        seed=seed,
        global_solver=global_solver,
    )
    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    order_ledger = load_ledger(ledger_path)  # Feature 003: cross-checked against the proven slice
    index = ReconIndex(recon_rows)
    solver_out: dict = {}
    attributions = attribute_all(
        lines,
        index,
        cfg.threshold,
        global_solver=cfg.global_solver,
        solver_result_out=solver_out if cfg.global_solver else None,
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

"""Reusable reconciliation entry point shared by the CLI and the web app.

Runs the full pipeline over three file paths and returns the report as a plain dict.
Read-only toward money; deterministic on the --no-ai path. The web layer writes uploads
to a temp dir, calls this, then deletes them — nothing is persisted.
"""

from __future__ import annotations

from engine.attribute import attribute_all
from engine.cli import _build_report
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
) -> dict:
    """Ingest → attribute → reconcile → fee-GST → exceptions; return report.to_dict()."""
    cfg = build_config(no_ai=no_ai, provider=provider, model=model, threshold=threshold, seed=seed)
    lines = load_bank(bank_path)
    recon_rows = load_recon(recon_path)
    load_ledger(ledger_path)  # validated; used by later phases
    index = ReconIndex(recon_rows)
    attributions = attribute_all(lines, index, cfg.threshold)
    if cfg.use_ai:
        client = LLMClient(enabled=True, provider=cfg.provider, model=cfg.model, api_key=cfg.api_key)
        attributions = resolve_unknowns(attributions, {ln.key: ln for ln in lines}, index, client)
    report, _ledger = _build_report(cfg, lines, recon_rows, index, attributions)
    return report.to_dict()

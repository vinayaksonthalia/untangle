"""Property: order-ledger reconciliation is ADDITIVE, deterministic, and empty-safe (Feature 003).

The single most important invariant (SC-003): turning the ledger cross-check on must NOT change any
attribution or reconciliation verdict, nor the headline precision/recall/reconciled/fee-GST numbers.
It may only ADD exceptions.
"""

from __future__ import annotations

from engine.attribute import attribute_all
from engine.cli import build_report
from engine.config import build_config
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_ledger, load_recon
from engine.ledger import reconcile_ledger
from engine.models import ExceptionRecord
from engine.reconcile import reconcile

# Headline totals that MUST be identical with vs without the ledger step.
_INVARIANT_KEYS = [
    "by_rail_count", "by_rail_paise", "attributed", "abstained",
    "reconciled_count", "reconciled_paise", "unresolved_rzp_count",
    "fee_gst_recoverable_paise", "total_credit_paise",
]


def _run(order_ledger):
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42)
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    index = ReconIndex(recon_rows)
    attrs = attribute_all(lines, index, cfg.threshold)
    report, _ledger = build_report(cfg, lines, recon_rows, index, attrs, order_ledger)
    return report.to_dict()["totals"]


def test_ledger_step_changes_no_headline_metric():
    ledger = load_ledger("data/order_ledger.csv")
    without = _run([])
    with_ = _run(ledger)
    for k in _INVARIANT_KEYS:
        assert without[k] == with_[k], f"ledger step changed headline metric {k!r}"
    # It must ADD exceptions (the third file earns its place — SC-002).
    assert with_["exception_count"] > without["exception_count"]


def test_ledger_output_is_only_exceptions_and_deterministic():
    ledger = load_ledger("data/order_ledger.csv")
    recon_rows = load_recon("data/recon_report.json")
    lines = load_bank("data/bank_statement.csv")
    index = ReconIndex(recon_rows)
    attrs = attribute_all(lines, index, 0.55)
    results, _u, _s = reconcile({ln.key: ln for ln in lines}, attrs, recon_rows)
    out1 = reconcile_ledger(ledger, results, recon_rows)
    out2 = reconcile_ledger(ledger, results, recon_rows)
    assert all(isinstance(e, ExceptionRecord) for e in out1)
    assert out1 == out2, "reconcile_ledger must be deterministic"
    # Aggregated: at most one exception per class (≤4 total).
    assert len(out1) <= 3
    assert len({e.reason_code for e in out1}) == len(out1)


def test_empty_ledger_is_safe():
    recon_rows = load_recon("data/recon_report.json")
    assert reconcile_ledger([], [], recon_rows) == []

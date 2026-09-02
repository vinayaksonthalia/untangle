"""Test golden decision projections (seed 42 and sealed seed 1337).

Verifies that the refactored narration evidence pack produces 100% identical decision
projections (verdicts, confidences, tiers, signal names, abstentions, exception reasons,
and reconciliation outcomes) to the frozen pre-refactor baseline.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engine.service import reconcile_bytes
from eval.benchmark_generator import (
    _format_bank_statement_csv,
    _format_order_ledger_csv,
    _format_recon_json,
)
from generator import bank as BANK
from generator import build as B
from generator import config as C
from generator import noise as NOISE

_GOLDEN_FIXTURE = Path(__file__).parent.parent / "fixtures" / "golden_projections.json"


def _compute_projection(bank_bytes: bytes, recon_bytes: bytes, ledger_bytes: bytes, seed: int) -> dict:
    report = reconcile_bytes(bank_bytes, recon_bytes, ledger_bytes, seed=seed)

    attributions = sorted(report["attributions"], key=lambda a: a["line_key"])
    attr_projection = [
        {
            "line_key": a["line_key"],
            "rail": a["rail"],
            "confidence": round(a["confidence"], 4),
            "tier": a["tier"],
            "abstained": a["abstained"],
            "signals": sorted(e["signal"] for e in a.get("evidence", [])),
        }
        for a in attributions
    ]

    exceptions = sorted(
        report.get("exceptions", []),
        key=lambda e: (e.get("line_key", ""), e.get("reason_code", "")),
    )
    exc_projection = [
        {
            "line_key": e.get("line_key", ""),
            "reason_code": e.get("reason_code", ""),
            "severity": e.get("severity", ""),
            "amount_paise": e.get("amount_paise"),
        }
        for e in exceptions
    ]

    reconciliations = sorted(report.get("reconciliations", []), key=lambda r: r["line_key"])
    rec_projection = [
        {
            "line_key": r["line_key"],
            "balanced": r.get("balanced", False),
            "credit_amount_paise": r.get("credit_amount_paise", 0),
            "covered_net_paise": r.get("covered_net_paise", 0),
            "residual_paise": r.get("residual_paise", 0),
            "covered_entities_count": len(r.get("covered_entity_ids", [])),
            "covered_rows_count": len(r.get("covered_row_ids", [])),
        }
        for r in reconciliations
    ]

    totals = report["totals"]

    canonical_repr = json.dumps(
        {
            "attributions": attr_projection,
            "exceptions": exc_projection,
            "reconciliations": rec_projection,
            "totals": totals,
        },
        sort_keys=True,
    )
    projection_sha256 = hashlib.sha256(canonical_repr.encode()).hexdigest()

    return {
        "projection_sha256": projection_sha256,
        "summary": {
            "n_bank_lines": totals["n_bank_lines"],
            "attributed": totals["attributed"],
            "abstained": totals["abstained"],
            "by_rail_count": totals["by_rail_count"],
            "reconciled_count": totals["reconciled_count"],
            "reconciled_paise": totals["reconciled_paise"],
            "fee_gst_recoverable_paise": totals["fee_gst_recoverable_paise"],
            "exception_count": totals["exception_count"],
            "exceptions_by_reason": totals["exceptions_by_reason"],
        },
        "decision_projection": {
            "attributions": attr_projection,
            "exceptions": exc_projection,
            "reconciliations": rec_projection,
            "totals": totals,
        },
    }


def test_seed_42_golden_decision_projection():
    """Assert seed 42 dev dataset produces the exact frozen decision projection."""
    with open(_GOLDEN_FIXTURE, encoding="utf-8") as f:
        golden = json.load(f)

    cfg42 = C.Config(seed=42, scale=1.0)
    built42 = B.build(cfg42)
    bank42, _ = BANK.build_bank_and_truth(cfg42, built42)
    ledger42, _ = NOISE.corrupt_ledger(cfg42, built42["orders"])
    bank_bytes = _format_bank_statement_csv(bank42)
    recon_bytes = _format_recon_json(built42["recon_rows"])
    ledger_bytes = _format_order_ledger_csv(ledger42)

    proj = _compute_projection(bank_bytes, recon_bytes, ledger_bytes, seed=42)

    expected = golden["seed_42_dev"]
    assert proj["projection_sha256"] == expected["projection_sha256"]
    assert proj["summary"] == expected["summary"]
    assert proj["decision_projection"]["attributions"] == expected["decision_projection"]["attributions"]
    assert proj["decision_projection"]["exceptions"] == expected["decision_projection"]["exceptions"]
    assert proj["decision_projection"]["reconciliations"] == expected["decision_projection"]["reconciliations"]
    assert proj["decision_projection"]["totals"] == expected["decision_projection"]["totals"]


def test_seed_1337_sealed_golden_decision_projection():
    """Assert seed 1337 sealed holdout dataset produces the exact frozen decision projection."""
    with open(_GOLDEN_FIXTURE, encoding="utf-8") as f:
        golden = json.load(f)

    cfg1337 = C.Config(seed=1337, scale=1.0)
    built1337 = B.build(cfg1337)
    bank1337, _ = BANK.build_bank_and_truth(cfg1337, built1337)
    ledger1337, _ = NOISE.corrupt_ledger(cfg1337, built1337["orders"])
    bank_bytes = _format_bank_statement_csv(bank1337)
    recon_bytes = _format_recon_json(built1337["recon_rows"])
    ledger_bytes = _format_order_ledger_csv(ledger1337)

    proj = _compute_projection(bank_bytes, recon_bytes, ledger_bytes, seed=1337)

    expected = golden["seed_1337_sealed"]
    assert proj["projection_sha256"] == expected["projection_sha256"]
    assert proj["summary"] == expected["summary"]
    assert proj["decision_projection"]["attributions"] == expected["decision_projection"]["attributions"]
    assert proj["decision_projection"]["exceptions"] == expected["decision_projection"]["exceptions"]
    assert proj["decision_projection"]["reconciliations"] == expected["decision_projection"]["reconciliations"]
    assert proj["decision_projection"]["totals"] == expected["decision_projection"]["totals"]

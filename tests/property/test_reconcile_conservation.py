"""Conservation invariants for reconciliation on the real generated batch (spec US2).

No recon row is covered twice; every reconciled credit balances to the paise (within the
drift tolerance); and every razorpay-attributed credit is partitioned into exactly one of
{reconciled, unresolved}. Deterministic dataset, so this doubles as an integration test.
"""

from __future__ import annotations

import os

import pytest

from engine.attribute import attribute_all
from engine.config import DEFAULT_THRESHOLD
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_recon
from engine.models import Rail
from engine.reconcile import _DRIFT_TOLERANCE_PAISE, reconcile

DATA = "data"
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(DATA, "bank_statement.csv")),
    reason="run `python -m generator.generate --seed 42 --out data` first",
)


def _run():
    lines = load_bank(os.path.join(DATA, "bank_statement.csv"))
    recon = load_recon(os.path.join(DATA, "recon_report.json"))
    attrs = attribute_all(lines, ReconIndex(recon), DEFAULT_THRESHOLD)
    lines_by_key = {ln.key: ln for ln in lines}
    results, unresolved, _ = reconcile(lines_by_key, attrs, recon)
    return lines, recon, attrs, results, unresolved


def test_no_recon_row_covered_twice():
    _, _, _, results, _ = _run()
    seen: set[tuple[str, str]] = set()
    for r in results:
        for eid in r.covered_entity_ids:
            key = tuple(eid)
            assert key not in seen, f"recon row {key} covered by two credits"
            seen.add(key)


def test_every_reconciliation_balances_to_the_paise():
    _, _, _, results, _ = _run()
    for r in results:
        assert abs(r.residual_paise) <= _DRIFT_TOLERANCE_PAISE
        assert r.covered_net_paise + r.residual_paise == r.credit_amount_paise
        assert r.balanced is True


def test_razorpay_credits_partition_into_reconciled_or_unresolved():
    _, _, attrs, results, unresolved = _run()
    rzp_keys = {a.line_key for a in attrs if a.rail == Rail.RAZORPAY_SETTLEMENT.value}
    reconciled_keys = {r.line_key for r in results}
    unresolved_keys = set(unresolved)
    assert reconciled_keys.isdisjoint(unresolved_keys)
    assert reconciled_keys | unresolved_keys == rzp_keys        # exact partition, nothing lost

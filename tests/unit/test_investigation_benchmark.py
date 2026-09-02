"""Regression coverage for the additive exception-investigation benchmark."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from engine.service import reconcile_bytes
from eval.metrics import score
from generator.config import Config
from generator.generate import run

_SEED42_CORE_HASHES = {
    "recon_report.json": "3d7e03fe7f5af77309cdcc5c7724cf4d9151bc24d30bdbf4c006e5091224de76",
    "order_ledger.csv": "112a0b7226c395664199cd10bd5b74ca3e295ef762c965358b2036769c2bb808",
    "bank_statement.csv": "2b61d9633a1e577f660df63c40f4b3316e5a4cfc5d5179c825e7f86b6f53fdc5",
    "ground_truth.json": "06efe5477a7b5f9ae2a5629b8fdd1ad4065a2b051810d8bff861c030bfede7d6",
}


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seed42_investigation_cases_resolve_without_mutating_core_benchmark(tmp_path):
    manifest = run(Config(seed=42, scale=1.0), str(tmp_path))

    # The companion dataset is strictly additive: the established attribution benchmark remains
    # byte-for-byte identical, so its attribution/reconciliation/fee-GST metrics cannot drift.
    for name, expected in _SEED42_CORE_HASHES.items():
        assert _sha256(tmp_path / name) == expected
        assert manifest["outputs"][name]["sha256"] == expected

    inv_dir = tmp_path / "investigation"
    report = reconcile_bytes(
        (inv_dir / "bank_statement.csv").read_bytes(),
        (inv_dir / "recon_report.json").read_bytes(),
        (inv_dir / "order_ledger.csv").read_bytes(),
        seed=42,
    )
    metrics = score(
        report,
        str(inv_dir / "ground_truth.json"),
        str(inv_dir / "bank_statement.csv"),
    )["investigation_resolution"]

    expected_causes = {
        "mdr_fee_drift",
        "cross_cycle_refund_lag",
        "on_hold_release",
        "dispute_deduction",
        "partial_capture",
        "rolling_reserve",
        "unexplained",
    }
    assert set(metrics["per_class"]) == expected_causes
    assert metrics["support"] == metrics["resolved"] == 7
    assert metrics["accuracy"] == 1.0
    assert metrics["balanced_or_abstained"] == 7
    assert all(
        v == {"support": 1, "resolved": 1, "balanced": 1} for v in metrics["per_class"].values()
    )

    investigations = {item["root_cause"]: item for item in report["investigations"]}
    for cause in expected_causes - {"unexplained"}:
        entry = investigations[cause]["corrective_entry"]
        assert entry["balanced"] is True
        assert sum(Decimal(line["debit_inr"]) for line in entry["lines"]) == sum(
            Decimal(line["credit_inr"]) for line in entry["lines"]
        )
    assert investigations["unexplained"]["corrective_entry"] is None


def test_investigation_ground_truth_is_explicit_and_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    run(Config(seed=42, scale=1.0), str(first))
    run(Config(seed=42, scale=1.0), str(second))
    truth_a = (first / "investigation" / "ground_truth.json").read_bytes()
    truth_b = (second / "investigation" / "ground_truth.json").read_bytes()
    assert truth_a == truth_b
    labels = json.loads(truth_a)["labels"]
    assert all(label.get("intended_root_cause") for label in labels)
    assert all(isinstance(label.get("expected_variance_paise"), int) for label in labels)

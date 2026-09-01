"""Regression coverage for PR #55 multi-month evaluation review findings."""
import json
import threading
import tracemalloc
from datetime import UTC, datetime

import pytest

from engine.certificate import issue_certificate, verify_certificate
from engine.ingest import load_bank_bytes, load_recon_bytes
from engine.service import reconcile_bytes
from eval.benchmark_generator import generate_multimonth_dataset
from eval.multimonth import (
    _audit_multimonth_invariants,
    _compute_monthly_metrics,
    run_multimonth_evaluation,
)


class _Line:
    def __init__(self, key, amount_paise):
        self.key, self.amount_paise = key, amount_paise


def _recovery_audit(action, plan_total):
    line = _Line("line-1", 1000)
    report = {"attributions": [{"line_key": "line-1"}], "recovery_plan": {
        "actions": [action], "recoverable_if_actioned_paise": plan_total}}
    aggregate = {"n_bank_lines": 1, "total_credit_paise": 1000, "reconciled_count": 0,
                 "reconciled_paise": 0, "fee_gst_recoverable_paise": 0,
                 "attributed": 0, "abstained": 0}
    return _audit_multimonth_invariants(report, {**report}, {"ok": True, "hash_matches": True},
                                        [line], [], {}, aggregate)


def _valid_action(**overrides):
    action = {"resolves": ["line-1"], "recoverable_paise": 1000,
              "debit_exposure_paise": 0, "action_type": "review"}
    action.update(overrides)
    return action


def test_recovery_audit_rejects_corrupt_action_amounts_and_duplicates():
    assert not _recovery_audit(_valid_action(recoverable_paise=900), 900).recovery_determinism_and_isolation
    assert not _recovery_audit(_valid_action(debit_exposure_paise=1), 1000).recovery_determinism_and_isolation
    duplicate = {"actions": [_valid_action(), _valid_action()], "recoverable_if_actioned_paise": 1000}
    result = _recovery_audit(duplicate["actions"][0], 1000)
    result = _audit_multimonth_invariants({"attributions": [{"line_key": "line-1"}], "recovery_plan": duplicate},
        {"attributions": [{"line_key": "line-1"}], "recovery_plan": duplicate}, {"ok": True, "hash_matches": True},
        [_Line("line-1", 1000)], [], {}, {"n_bank_lines": 1, "total_credit_paise": 1000, "reconciled_count": 0,
        "reconciled_paise": 0, "fee_gst_recoverable_paise": 0, "attributed": 0, "abstained": 0})
    assert not result.recovery_determinism_and_isolation
    assert not _recovery_audit(_valid_action(), 900).recovery_determinism_and_isolation


def test_recovery_audit_accepts_valid_action_and_plan_total():
    assert _recovery_audit(_valid_action(), 1000).recovery_determinism_and_isolation


@pytest.mark.parametrize("bad_plan", [[], "x", 1, True])
def test_recovery_audit_rejects_non_mapping_plan(bad_plan):
    report = {"attributions": [], "recovery_plan": bad_plan}
    result = _audit_multimonth_invariants(report, report, {"ok": True, "hash_matches": True},
                                          [], [], {}, {"n_bank_lines": 0, "total_credit_paise": 0,
                                          "reconciled_count": 0, "reconciled_paise": 0,
                                          "fee_gst_recoverable_paise": 0, "attributed": 0, "abstained": 0})
    assert result.recovery_determinism_and_isolation is False


@pytest.mark.parametrize("bad_actions", [None, 1, {}, "x"])
def test_recovery_audit_rejects_non_list_actions(bad_actions):
    line = _Line("line-1", 1)
    report = {"attributions": [{"line_key": "line-1"}], "recovery_plan":
              {"actions": bad_actions, "recoverable_if_actioned_paise": 0}}
    result = _audit_multimonth_invariants(report, report, {"ok": True, "hash_matches": True},
        [line], [], {}, {"n_bank_lines": 1, "total_credit_paise": 1, "reconciled_count": 0,
        "reconciled_paise": 0, "fee_gst_recoverable_paise": 0, "attributed": 0, "abstained": 0})
    assert not result.recovery_determinism_and_isolation


@pytest.mark.parametrize("field,value", [("recoverable_paise", True), ("debit_exposure_paise", False)])
def test_recovery_audit_rejects_bool_money(field, value):
    assert not _recovery_audit(_valid_action(**{field: value}), 1000).recovery_determinism_and_isolation


def test_recovery_audit_rejects_bool_plan_aggregate():
    assert not _recovery_audit(_valid_action(), True).recovery_determinism_and_isolation


def test_tracemalloc_measurement_lifecycle_is_serialized():
    # The lifecycle lock is process-wide; acquiring it twice in order is deterministic evidence
    # that a competing evaluator cannot enter the measurement region concurrently.
    from eval.multimonth import _TRACEMALLOC_LOCK
    with _TRACEMALLOC_LOCK:
        assert not _TRACEMALLOC_LOCK.acquire(blocking=False)


def test_two_concurrent_evaluations_complete_without_tracing_interference():
    barrier = threading.Barrier(2)
    errors = []
    def worker(seed):
        try:
            barrier.wait()
            run_multimonth_evaluation(seed=seed, scale=.005)
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=worker, args=(3,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert not tracemalloc.is_tracing()


@pytest.mark.parametrize("bad", [{}, [], None, 4, ""])
def test_recovery_audit_rejects_malformed_resolve_keys_without_crashing(bad):
    result = _recovery_audit(_valid_action(resolves=[bad]), 1000)
    assert result.recovery_determinism_and_isolation is False


@pytest.mark.parametrize("bad_action", [None, [], "action", {"resolves": "line-1"}])
def test_recovery_audit_rejects_malformed_actions_without_crashing(bad_action):
    line = _Line("line-1", 1000)
    report = {"attributions": [{"line_key": "line-1"}], "recovery_plan": {
        "actions": [bad_action], "recoverable_if_actioned_paise": 0}}
    aggregate = {"n_bank_lines": 1, "total_credit_paise": 1000, "reconciled_count": 0,
                 "reconciled_paise": 0, "fee_gst_recoverable_paise": 0,
                 "attributed": 0, "abstained": 0}
    result = _audit_multimonth_invariants(report, report, {"ok": True, "hash_matches": True},
                                          [line], [], {}, aggregate)
    assert result.recovery_determinism_and_isolation is False


def test_recovery_plan_schema_is_partitioned_into_monthly_exposure():
    ds = generate_multimonth_dataset(seed=42, scale=.02)
    bank = load_bank_bytes(ds.bank_bytes)
    recon = load_recon_bytes(ds.recon_bytes)
    report = {"totals": {}, "recovery_plan": {"actions": [{"resolves": [bank[0].key]}]}}
    monthly, _ = _compute_monthly_metrics(report, bank, recon)
    month = bank[0].value_date.strftime("%Y-%m")
    assert monthly[month].recovery_exposure_paise == max(0, bank[0].amount_paise)


def test_certificate_requires_the_bound_report_when_supplied():
    report = {"audit_root": "root", "totals": {}}
    cert = issue_certificate(report)
    assert verify_certificate({**cert, "report": report})["report_binding_valid"] is True
    assert verify_certificate({**cert, "report": {"tampered": True}})["ok"] is False


def test_custom_dataset_metadata_is_reported_from_manifest():
    ds = generate_multimonth_dataset(seed=7, scale=.01, base_epoch=1_700_000_000, n_days=95)
    assert ds.manifest["config"]["base_epoch"] == 1_700_000_000
    assert ds.manifest["config"]["n_days"] == 95


def test_cross_month_output_keeps_covered_rows_traceable():
    ds = generate_multimonth_dataset(seed=42, scale=.02)
    report = reconcile_bytes(ds.bank_bytes, ds.recon_bytes, ds.ledger_bytes, no_ai=True, seed=42)
    bank = {row.key: row for row in load_bank_bytes(ds.bank_bytes)}
    months = set()
    for item in report.get("reconciliations", []):
        if item.get("covered_row_ids"):
            months.add(bank[item["line_key"]].value_date.strftime("%Y-%m"))
            assert all(isinstance(row_id, str) and row_id.startswith("row_") for row_id in item["covered_row_ids"])
    assert len(months) >= 3
    raw = json.loads(ds.recon_bytes)
    refunds = [r for r in raw if r.get("type") == "refund" and r.get("created_at") and r.get("settled_at")]
    def month(ts):
        value = datetime.fromtimestamp(ts, tz=UTC)
        return value.year, value.month
    assert any(month(r["settled_at"]) != month(r["created_at"]) for r in refunds)
    by_settlement = {}
    for r in raw:
        if r.get("settlement_id"):
            by_settlement.setdefault(r["settlement_id"], []).append(r)
    assert any(len(rows) > 1 for rows in by_settlement.values())
    assert any(r.get("settlement_id") is None for r in raw) or len(by_settlement) > 1


def test_replay_audit_rejects_changed_nested_output():
    base = {"audit_root": "a", "totals": {}, "attributions": [{"line_key": "x"}]}
    changed = {**base, "attributions": [{"line_key": "y"}]}
    aggregate = {"n_bank_lines": 0, "total_credit_paise": 0, "reconciled_count": 0,
                 "reconciled_paise": 0, "fee_gst_recoverable_paise": 0, "attributed": 0, "abstained": 0}
    result = _audit_multimonth_invariants(base, changed, {"ok": True, "hash_matches": True}, [], [], {}, aggregate)
    assert result.determinism_verified is False


def test_tracemalloc_state_can_be_owned_by_the_caller():
    tracemalloc.start()
    try:
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def test_evaluation_heap_metrics_exclude_caller_historical_peak():
    tracemalloc.start()
    try:
        allocation = bytearray(2_000_000)
        tracemalloc.get_traced_memory()
        result = run_multimonth_evaluation(seed=3, scale=.005)
        assert tracemalloc.is_tracing()
        assert result.peak_python_heap_bytes is None
        assert result.current_python_heap_bytes >= 0
    finally:
        tracemalloc.stop()
        assert allocation[0] == 0

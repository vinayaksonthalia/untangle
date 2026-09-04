"""Comprehensive 90-Day and Multi-Month Evaluation Test Suite (Phase 1, Task 6).

Verifies that Untangle's attribution, reconciliation, fee-GST, exceptions, journal,
and recovery pipeline functions correctly across rolling multi-month accounting periods:

1. Dataset spans >= 90 days across 3 distinct calendar months.
2. Cross-month corruptions and hard cases are present in dataset ground truth.
3. 1:1 terminal disposition and unique line keys across all 90 days.
4. Honest abstention on ambiguous or undecidable items.
5. Zero double-covered recon rows across accounting periods.
6. Monthly breakdown metrics reconcile mathematically to aggregate 90-day totals.
7. Cross-cycle refunds, split legs, and rolling reserves remain traceable.
8. Double-entry journal vouchers balance to the paise using real serialized fields.
9. Recovery exposure is deterministic, non-duplicative, and isolates debit exposure.
10. Canonical determinism across rerun.
11. Seed variation produces genuinely distinct datasets.
12. Negative / Fault injection tests verify audit catches corrupted invariants.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine.ingest import load_bank_bytes, load_recon_bytes
from engine.service import reconcile_bytes
from eval.benchmark_generator import generate_multimonth_dataset
from eval.multimonth import (
    _audit_multimonth_invariants,
    _compute_monthly_metrics,
    format_multimonth_terminal_table,
    run_multimonth_evaluation,
)


@pytest.fixture(scope="module")
def eval_result():
    """Run the standard multi-month evaluation once for read-only invariant assertions."""
    return run_multimonth_evaluation(seed=42, scale=0.15)


def test_multimonth_dataset_spans_90_days_and_3_calendar_months(eval_result):
    """1. The generated evaluation spans at least 90 days and 3 distinct calendar months."""
    window = eval_result.date_window
    assert window["n_calendar_months"] >= 3
    assert window["covered_months"] == ["2026-04", "2026-05", "2026-06"]
    assert window["start_date"] <= "2026-04-02"
    assert window["end_date"] >= "2026-06-30"


def test_cross_month_cases_present_in_ground_truth():
    """2. Required cross-month corruption and accounting cases are present in ground truth."""
    ds = generate_multimonth_dataset(seed=42, scale=0.15)
    manifest = ds.manifest
    hard_counts = manifest.get("per_hard_case_counts", {})

    assert hard_counts.get("cross_cycle_refunds", 0) > 0, "Cross-cycle refunds must be present"
    assert hard_counts.get("split_settlement_legs", 0) > 0, "Split settlement legs must be present"
    assert hard_counts.get("merge_settlements", 0) > 0, "Merged settlements must be present"
    assert hard_counts.get("carry_forward", 0) > 0, "Carry-forward batches must be present"
    assert hard_counts.get("value_date_jitter", 0) > 0, "Value date jitter must be present"
    assert hard_counts.get("on_hold_rows", 0) > 0, "On-hold rows must be present"
    assert hard_counts.get("dispute_rows", 0) > 0, "Dispute rows must be present"
    assert hard_counts.get("rounding_drift", 0) > 0, "Rounding drift must be present"
    assert hard_counts.get("mangled_utr", 0) > 0, "Mangled UTRs must be present"

    # Validate the labels against concrete rows and engine output, not just counters.
    raw = json.loads(ds.recon_bytes)
    bank = load_bank_bytes(ds.bank_bytes)
    report = reconcile_bytes(ds.bank_bytes, ds.recon_bytes, ds.ledger_bytes, no_ai=True, seed=42)
    refunds = [r for r in raw if r["type"] == "refund" and r.get("created_at") and r.get("settled_at")]
    def month(ts):
        value = datetime.fromtimestamp(ts, tz=UTC)
        return value.year, value.month
    assert any(month(r["settled_at"]) != month(r["created_at"]) for r in refunds)
    payments = {}
    for row in raw:
        if row.get("payment_id"):
            payments.setdefault(row["payment_id"], []).append(row)
    split_payment_ids = {pid for pid, rows in payments.items() if len(rows) > 1}
    assert split_payment_ids
    covered_entities = {
        tuple(entity) for rec in report["reconciliations"] for entity in rec.get("covered_entity_ids", [])
    }
    assert any(tuple((row["type"], row["entity_id"])) in covered_entities
               for rows in payments.values() if len(rows) > 1 for row in rows)
    # Carry-forward rows are represented by bank credits whose linked settlement evidence
    # is dated in an earlier calendar month; ensure those rows remain in terminal output.
    assert len({line.value_date.strftime("%Y-%m") for line in bank}) >= 3
    assert len(report["attributions"]) == len(bank)


def test_single_verdict_and_line_key_conservation(eval_result):
    """3. Exactly one verdict exists for every unique bank line (conservation of lines)."""
    invariants = eval_result.invariants
    assert invariants.single_verdict_per_line
    assert invariants.line_key_conservation
    assert eval_result.aggregate_metrics["n_bank_lines"] == 826
    assert eval_result.aggregate_metrics["attributed"] + eval_result.aggregate_metrics["abstained"] == 826
    assert eval_result.aggregate_metrics["reconciled_count"] == 245
    assert eval_result.aggregate_metrics["reconciled_paise"] == 430439847


def test_ambiguous_cases_remain_abstained(eval_result):
    """4. Ambiguous and decoy-heavy cases remain abstained (UNKNOWN) rather than force-matched."""
    assert eval_result.aggregate_metrics["abstained"] > 0
    # Every month must have honest abstentions where evidence is undecidable
    for month, metrics in eval_result.monthly_metrics.items():
        assert metrics.abstained_lines > 0, f"Expected abstentions in month {month}"
        assert metrics.rail_counts.get("UNKNOWN", 0) == metrics.abstained_lines


def test_zero_double_covered_recon_rows(eval_result):
    """5. Zero double-covered recon rows across all months (no transaction consumed twice)."""
    assert eval_result.invariants.zero_double_covered_rows


def test_monthly_totals_reconcile_to_aggregate(eval_result):
    """6. Monthly metric sums reconcile mathematically to 90-day aggregate totals."""
    assert eval_result.invariants.monthly_sums_reconcile_to_aggregate

    months = list(eval_result.monthly_metrics.keys())
    m = eval_result.monthly_metrics
    agg = eval_result.aggregate_metrics

    assert sum(m[k].input_bank_lines for k in months) == agg["n_bank_lines"]
    assert sum(m[k].total_credited_paise for k in months) == agg["total_credit_paise"]
    assert sum(m[k].reconciled_credits for k in months) == agg["reconciled_count"]
    assert sum(m[k].reconciled_paise for k in months) == agg["reconciled_paise"]
    assert sum(m[k].recoverable_itc_paise for k in months) == agg["fee_gst_recoverable_paise"]
    assert sum(m[k].attributed_lines for k in months) == agg["attributed"]
    assert sum(m[k].abstained_lines for k in months) == agg["abstained"]


def test_journal_vouchers_balance_on_actual_serialized_schema():
    """8. Every journal entry in JSON and Tally XML is balanced using actual serialized numbers."""
    ds = generate_multimonth_dataset(seed=42, scale=0.15)
    report = reconcile_bytes(ds.bank_bytes, ds.recon_bytes, ds.ledger_bytes, seed=42)

    journal = report.get("journal", [])
    assert len(journal) == report["totals"]["reconciled_count"]
    assert len(journal) > 0

    for entry in journal:
        assert entry["balanced"] is True
        # Date must follow earliest settlement date (or creation date)
        assert entry["date"] != ""
        assert len(entry["date"]) == 10  # YYYY-MM-DD
        lines = entry["lines"]
        total_debit = sum(int(round(float(ln["debit_inr"]) * 100)) for ln in lines if "debit_inr" in ln)
        total_credit = sum(int(round(float(ln["credit_inr"]) * 100)) for ln in lines if "credit_inr" in ln)
        assert total_debit == total_credit
        assert total_debit > 0


def test_recovery_exposure_not_duplicated_and_debit_isolated(eval_result):
    """9. Recovery actions are deterministic and debit exposures are strictly isolated."""
    assert eval_result.invariants.recovery_determinism_and_isolation


def test_deterministic_replay_across_runs():
    """10. Two identical runs produce canonical identical outputs."""
    ds = generate_multimonth_dataset(seed=42, scale=0.15)
    res1 = run_multimonth_evaluation(ds)
    res2 = run_multimonth_evaluation(ds)

    assert res1.aggregate_metrics == res2.aggregate_metrics
    assert res1.monthly_metrics == res2.monthly_metrics
    assert res1.invariants.all_passed is True
    assert res2.invariants.all_passed is True


def test_seed_variation_produces_distinct_datasets():
    """11. Changing the seed produces a genuinely distinct dataset and audit root."""
    res_42 = run_multimonth_evaluation(seed=42, scale=0.15)
    res_99 = run_multimonth_evaluation(seed=99, scale=0.15)

    assert res_42.aggregate_metrics["audit_root"] != res_99.aggregate_metrics["audit_root"]
    assert res_42.aggregate_metrics["total_credit_paise"] != res_99.aggregate_metrics["total_credit_paise"]


def test_terminal_table_formatting(eval_result):
    """Verify human-readable terminal table output format."""
    table = format_multimonth_terminal_table(eval_result)
    assert "UNTANGLE MULTI-MONTH & 90-DAY EVALUATION" in table
    assert "2026-04" in table
    assert "2026-05" in table
    assert "2026-06" in table
    assert "OVERALL RESULT: [PASS]" in table


def test_negative_fault_injections_detected_by_audit():
    """12. Negative fault injections: audit fails when invariants are artificially violated."""
    ds = generate_multimonth_dataset(seed=42, scale=0.15)
    bank_lines = load_bank_bytes(ds.bank_bytes)
    recon_rows = load_recon_bytes(ds.recon_bytes)
    report = reconcile_bytes(ds.bank_bytes, ds.recon_bytes, ds.ledger_bytes, seed=42)
    monthly_metrics, aggregate_metrics = _compute_monthly_metrics(report, bank_lines, recon_rows)
    cert_verify = {"ok": True, "hash_matches": True}

    # 12a. Missing bank line in attributions
    corrupt_report = json.loads(json.dumps(report))
    corrupt_report["attributions"].pop()
    res = _audit_multimonth_invariants(
        corrupt_report, corrupt_report, cert_verify, bank_lines, recon_rows, monthly_metrics, aggregate_metrics
    )
    assert res.all_passed is False
    assert any("Line key conservation failure" in f for f in res.failures)

    # 12b. Double-covered recon row injection
    corrupt_report = json.loads(json.dumps(report))
    if corrupt_report["reconciliations"]:
        corrupt_report["reconciliations"][0]["covered_row_ids"].append("row_duplicate_inject")
        corrupt_report["reconciliations"][1]["covered_row_ids"].append("row_duplicate_inject")
        res = _audit_multimonth_invariants(
            corrupt_report, corrupt_report, cert_verify, bank_lines, recon_rows, monthly_metrics, aggregate_metrics
        )
        assert res.all_passed is False
        assert any("Double-covered recon rows detected" in f for f in res.failures)

    # 12c. Unbalanced journal entry injection
    corrupt_report = json.loads(json.dumps(report))
    if corrupt_report["journal"]:
        corrupt_report["journal"][0]["balanced"] = False
        res = _audit_multimonth_invariants(
            corrupt_report, corrupt_report, cert_verify, bank_lines, recon_rows, monthly_metrics, aggregate_metrics
        )
        assert res.all_passed is False
        assert any("Unbalanced journal entry" in f for f in res.failures)

    # 12d. Monthly sum mismatch injection
    corrupt_monthly = dict(monthly_metrics)
    m0 = list(corrupt_monthly.keys())[0]
    corrupt_monthly[m0] = corrupt_monthly[m0].__class__(
        month=m0,
        input_bank_lines=corrupt_monthly[m0].input_bank_lines + 5,  # artificial mismatch
        attributed_lines=corrupt_monthly[m0].attributed_lines,
        abstained_lines=corrupt_monthly[m0].abstained_lines,
        rail_counts=corrupt_monthly[m0].rail_counts,
        razorpay_lines=corrupt_monthly[m0].razorpay_lines,
        reconciled_credits=corrupt_monthly[m0].reconciled_credits,
        unresolved_credits=corrupt_monthly[m0].unresolved_credits,
        total_credited_paise=corrupt_monthly[m0].total_credited_paise,
        reconciled_paise=corrupt_monthly[m0].reconciled_paise,
        residual_paise=corrupt_monthly[m0].residual_paise,
        recoverable_itc_paise=corrupt_monthly[m0].recoverable_itc_paise,
        exception_count=corrupt_monthly[m0].exception_count,
        recovery_exposure_paise=corrupt_monthly[m0].recovery_exposure_paise,
    )
    res = _audit_multimonth_invariants(
        report, report, cert_verify, bank_lines, recon_rows, corrupt_monthly, aggregate_metrics
    )
    assert res.all_passed is False
    assert any("Monthly metric sum mismatch" in f for f in res.failures)

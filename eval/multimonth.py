"""Extended 90-Day and Multi-Month Evaluation (Phase 1, Task 6).

Evaluates Untangle's reconciliation and accounting pipeline across rolling accounting periods,
month boundaries, carry-forwards, delayed settlements, refunds, disputes, reserves, and repeated identifiers.

Spans 90 days across 3 distinct calendar months (e.g. April, May, June 2026).

Usage:
    python -m eval.multimonth
    python -m eval.multimonth --seed 42 --scale 0.15
    python -m eval.multimonth --json
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
import tracemalloc
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from engine.certificate import issue_certificate, verify_certificate
from engine.covered import rows_by_canonical_id
from engine.ingest import load_bank_bytes, load_recon_bytes
from engine.service import reconcile_bytes
from eval.benchmark_generator import BenchmarkDataset, generate_multimonth_dataset

_TRACEMALLOC_LOCK = threading.Lock()

MULTIMONTH_EVAL_VERSION = "1.0.0"


@dataclass(frozen=True)
class MonthlyMetrics:
    """Reconciliation and attribution metrics for a single calendar month."""

    month: str
    input_bank_lines: int
    attributed_lines: int
    abstained_lines: int
    rail_counts: dict[str, int]
    razorpay_lines: int
    reconciled_credits: int
    unresolved_credits: int
    total_credited_paise: int
    reconciled_paise: int
    residual_paise: int
    recoverable_itc_paise: int
    exception_count: int
    recovery_exposure_paise: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_credited_inr"] = round(self.total_credited_paise / 100, 2)
        d["reconciled_inr"] = round(self.reconciled_paise / 100, 2)
        d["residual_inr"] = round(self.residual_paise / 100, 2)
        d["recoverable_itc_inr"] = round(self.recoverable_itc_paise / 100, 2)
        d["recovery_exposure_inr"] = round(self.recovery_exposure_paise / 100, 2)
        return d


@dataclass(frozen=True)
class MultiMonthInvariantResults:
    """Status of mathematical, period-boundary, and determinism invariants."""

    all_passed: bool
    single_verdict_per_line: bool
    line_key_conservation: bool
    paise_conservation: bool
    zero_double_covered_rows: bool
    journal_balanced: bool
    recovery_determinism_and_isolation: bool
    certificate_valid: bool
    determinism_verified: bool
    monthly_sums_reconcile_to_aggregate: bool
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultiMonthEvaluationResult:
    """Complete multi-month evaluation report."""

    version: str
    seed: int
    scale: float
    base_epoch: int
    n_days: int
    date_window: dict[str, str]
    duration_seconds: float
    peak_python_heap_bytes: int | None
    current_python_heap_bytes: int
    input_metrics: dict[str, Any]
    monthly_metrics: dict[str, MonthlyMetrics]
    aggregate_metrics: dict[str, Any]
    invariants: MultiMonthInvariantResults
    environment: dict[str, str]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "seed": self.seed,
            "scale": self.scale,
            "base_epoch": self.base_epoch,
            "n_days": self.n_days,
            "date_window": self.date_window,
            "duration_seconds": round(self.duration_seconds, 4),
            "peak_python_heap_bytes": self.peak_python_heap_bytes,
            "peak_python_heap_mb": (
                round(self.peak_python_heap_bytes / (1024 * 1024), 2)
                if self.peak_python_heap_bytes is not None
                else None
            ),
            "current_python_heap_bytes": self.current_python_heap_bytes,
            "input_metrics": self.input_metrics,
            "monthly_metrics": {m: metrics.to_dict() for m, metrics in self.monthly_metrics.items()},
            "aggregate_metrics": self.aggregate_metrics,
            "invariants": self.invariants.to_dict(),
            "environment": self.environment,
            "limitations": self.limitations,
        }


def _compute_monthly_metrics(
    report: dict[str, Any],
    bank_lines: list,
    recon_rows: list,
) -> tuple[dict[str, MonthlyMetrics], dict[str, Any]]:
    """Partition bank lines, attributions, and reconciliations by statement month."""
    months_by_key = {ln.key: ln.value_date.strftime("%Y-%m") for ln in bank_lines}
    months = sorted(set(months_by_key.values()))
    rows_by_id = rows_by_canonical_id(recon_rows)

    monthly_data: dict[str, dict[str, Any]] = {
        m: {
            "month": m,
            "input_bank_lines": 0,
            "attributed_lines": 0,
            "abstained_lines": 0,
            "rail_counts": defaultdict(int),
            "razorpay_lines": 0,
            "reconciled_credits": 0,
            "unresolved_credits": 0,
            "total_credited_paise": 0,
            "reconciled_paise": 0,
            "residual_paise": 0,
            "recoverable_itc_paise": 0,
            "exception_count": 0,
            "recovery_exposure_paise": 0,
        }
        for m in months
    }

    for ln in bank_lines:
        m = months_by_key[ln.key]
        monthly_data[m]["input_bank_lines"] += 1
        if ln.is_credit:
            monthly_data[m]["total_credited_paise"] += ln.amount_paise

    for attr in report.get("attributions", []):
        lk = attr.get("line_key")
        if lk in months_by_key:
            m = months_by_key[lk]
            rail = attr.get("rail", "UNKNOWN")
            if rail == "UNKNOWN":
                monthly_data[m]["abstained_lines"] += 1
            else:
                monthly_data[m]["attributed_lines"] += 1
            monthly_data[m]["rail_counts"][rail] += 1
            if rail == "razorpay_settlement":
                monthly_data[m]["razorpay_lines"] += 1

    for rec in report.get("reconciliations", []):
        lk = rec.get("line_key")
        if lk in months_by_key:
            m = months_by_key[lk]
            if rec.get("balanced", False):
                monthly_data[m]["reconciled_credits"] += 1
                monthly_data[m]["reconciled_paise"] += rec.get("credit_amount_paise", 0)
                monthly_data[m]["residual_paise"] += abs(rec.get("residual_paise", 0))
                # Sum ITC from covering settlement rows
                covered_ids = rec.get("covered_row_ids", [])
                itc_sum = sum(
                    rows_by_id[rid].tax_paise
                    for rid in covered_ids
                    if rid in rows_by_id
                )
                monthly_data[m]["recoverable_itc_paise"] += itc_sum
            else:
                monthly_data[m]["unresolved_credits"] += 1

    for exc in report.get("exceptions", []):
        lk = exc.get("line_key")
        if lk and lk in months_by_key:
            m = months_by_key[lk]
            monthly_data[m]["exception_count"] += 1

    # Recovery actions item-level partition
    recovery = report.get("recovery_plan") or {}
    lines_by_key = {ln.key: ln for ln in bank_lines}
    for act in recovery.get("actions", []):
        for lk in act.get("resolves", []):
            if lk and lk in months_by_key:
                m = months_by_key[lk]
                monthly_data[m]["recovery_exposure_paise"] += max(0, lines_by_key[lk].amount_paise)

    metrics_by_month: dict[str, MonthlyMetrics] = {}
    for m in months:
        d = monthly_data[m]
        metrics_by_month[m] = MonthlyMetrics(
            month=m,
            input_bank_lines=d["input_bank_lines"],
            attributed_lines=d["attributed_lines"],
            abstained_lines=d["abstained_lines"],
            rail_counts=dict(sorted(d["rail_counts"].items())),
            razorpay_lines=d["razorpay_lines"],
            reconciled_credits=d["reconciled_credits"],
            unresolved_credits=d["unresolved_credits"],
            total_credited_paise=d["total_credited_paise"],
            reconciled_paise=d["reconciled_paise"],
            residual_paise=d["residual_paise"],
            recoverable_itc_paise=d["recoverable_itc_paise"],
            exception_count=d["exception_count"],
            recovery_exposure_paise=d["recovery_exposure_paise"],
        )

    # Compute aggregates from report totals
    totals = report.get("totals", {})
    aggregate_metrics = {
        "n_bank_lines": totals.get("n_bank_lines", len(bank_lines)),
        "n_recon_rows": totals.get("n_recon_rows", len(recon_rows)),
        "attributed": totals.get("attributed", 0),
        "abstained": totals.get("abstained", 0),
        "by_rail_count": totals.get("by_rail_count", {}),
        "reconciled_count": totals.get("reconciled_count", 0),
        "reconciled_paise": totals.get("reconciled_paise", 0),
        "reconciled_inr": round(totals.get("reconciled_paise", 0) / 100, 2),
        "unresolved_rzp_count": totals.get("unresolved_rzp_count", 0),
        "fee_gst_recoverable_paise": totals.get("fee_gst_recoverable_paise", 0),
        "fee_gst_recoverable_inr": round(totals.get("fee_gst_recoverable_paise", 0) / 100, 2),
        "total_credit_paise": totals.get("total_credit_paise", 0),
        "total_credit_inr": round(totals.get("total_credit_paise", 0) / 100, 2),
        "exception_count": totals.get("exception_count", len(report.get("exceptions", []))),
        "audit_root": report.get("audit_root", ""),
    }

    return metrics_by_month, aggregate_metrics


def _audit_multimonth_invariants(
    report: dict[str, Any],
    report_rerun: dict[str, Any],
    cert_verify: dict[str, Any],
    bank_lines: list,
    recon_rows: list,
    monthly_metrics: dict[str, MonthlyMetrics],
    aggregate_metrics: dict[str, Any],
) -> MultiMonthInvariantResults:
    """Audit all 90-day multi-month and period-boundary invariants."""
    failures: list[str] = []

    # 1. 1:1 Terminal verdict per line & line key conservation
    expected_keys = [ln.key for ln in bank_lines]
    attributions = report.get("attributions", [])
    actual_keys = [a.get("line_key") for a in attributions]
    single_verdict = (
        len(actual_keys) == len(expected_keys)
        and len(set(actual_keys)) == len(actual_keys)
        and set(actual_keys) == set(expected_keys)
    )
    if not single_verdict:
        failures.append(
            f"Line key conservation failure: expected {len(expected_keys)} distinct keys, got {len(actual_keys)}"
        )

    # 2. Paise conservation & residual bounds
    reconciliations = report.get("reconciliations", [])
    paise_conserved = True
    for rec in reconciliations:
        if rec.get("balanced", False):
            credit_paise = rec.get("credit_amount_paise", 0)
            covered_paise = rec.get("covered_net_paise", 0)
            residual = rec.get("residual_paise", 0)
            if credit_paise - covered_paise != residual or abs(residual) > 100:
                paise_conserved = False
                failures.append(
                    f"Paise conservation violated for line {rec.get('line_key')}: "
                    f"credit={credit_paise}, covered={covered_paise}, residual={residual}"
                )
                break

    # 3. Zero double-covered recon rows across all months
    claimed_row_ids: list[str] = []
    for rec in reconciliations:
        for rid in rec.get("covered_row_ids", []):
            claimed_row_ids.append(rid)
    no_double_covered = len(claimed_row_ids) == len(set(claimed_row_ids))
    if not no_double_covered:
        failures.append(
            f"Double-covered recon rows detected: {len(claimed_row_ids)} claimed vs {len(set(claimed_row_ids))} unique"
        )

    # 4. Double-entry journal balance on actual serialized schema
    journal = report.get("journal", [])
    journal_balanced = True
    if reconciliations and not journal:
        journal_balanced = False
        failures.append("Reconciliations exist but zero journal entries were emitted")
    for entry in journal:
        if not entry.get("balanced", False):
            journal_balanced = False
            failures.append(f"Unbalanced journal entry: {entry.get('ref')}")
            break
        # Verify debits == credits from lines
        lines = entry.get("lines", [])
        total_debit = sum(
            int(round(float(ln["debit_inr"]) * 100))
            for ln in lines
            if "debit_inr" in ln
        )
        total_credit = sum(
            int(round(float(ln["credit_inr"]) * 100))
            for ln in lines
            if "credit_inr" in ln
        )
        if total_debit != total_credit or total_debit <= 0:
            journal_balanced = False
            failures.append(
                f"Journal voucher math unbalanced for {entry.get('ref')}: {total_debit} != {total_credit}"
            )
            break

    # 5. Recovery determinism & debit exposure isolation
    recovery_ok = True
    raw_plan = report.get("recovery_plan")
    recovery_actions = raw_plan.get("actions", []) if isinstance(raw_plan, dict) else []
    plan = raw_plan if isinstance(raw_plan, dict) else {}
    if raw_plan is not None and not isinstance(raw_plan, dict):
        recovery_ok = False
        failures.append("Malformed recovery plan: expected mapping")
    if not isinstance(recovery_actions, list):
        recovery_ok = False
        failures.append("Malformed recovery plan actions: expected list")
        recovery_actions = []
    resolved: list[str] = []
    line_amounts = {line.key: line.amount_paise for line in bank_lines}
    for act in recovery_actions:
        if not isinstance(act, dict):
            recovery_ok = False
            failures.append(f"Malformed recovery action: {act!r}")
            continue
        keys = act.get("resolves", [])
        recoverable = act.get("recoverable_paise", -1)
        debit = act.get("debit_exposure_paise", -1)
        valid_keys = (isinstance(keys, list) and bool(keys)
                      and all(isinstance(key, str) and bool(key) for key in keys))
        if (not valid_keys or type(recoverable) is not int
                or type(debit) is not int or recoverable < 0 or debit < 0
                or any(key not in line_amounts for key in keys)
                or len(keys) != len(set(keys))
                or recoverable != sum(max(0, line_amounts[key]) for key in keys)
                or debit != sum(max(0, -line_amounts[key]) for key in keys)):
            recovery_ok = False
            failures.append(f"Invalid recovery action arithmetic: {act}")
        if valid_keys:
            resolved.extend(keys)
    if len(resolved) != len(set(resolved)):
        recovery_ok = False
        failures.append("Recovery actions resolve the same line more than once")
    distinct_recoverable = sum(max(0, line_amounts[key]) for key in set(resolved) if key in line_amounts)
    if type(plan.get("recoverable_if_actioned_paise")) is not int or plan.get("recoverable_if_actioned_paise") != distinct_recoverable:
        recovery_ok = False
        failures.append("Recovery plan aggregate does not match distinct resolved credits")

    # 6. Certificate validity
    cert_valid = cert_verify.get("ok", False) and cert_verify.get("hash_matches", False)
    if not cert_valid:
        failures.append(f"Close certificate verification failed: {cert_verify}")

    # 7. Determinism across reruns
    determinism_ok = (
        report.get("audit_root") == report_rerun.get("audit_root")
        and report.get("totals") == report_rerun.get("totals")
        and len(report.get("attributions", [])) == len(report_rerun.get("attributions", []))
        and len(report.get("reconciliations", [])) == len(report_rerun.get("reconciliations", []))
        and len(report.get("exceptions", [])) == len(report_rerun.get("exceptions", []))
        and len(report.get("investigations", [])) == len(report_rerun.get("investigations", []))
        and len(report.get("journal", [])) == len(report_rerun.get("journal", []))
        and report == report_rerun
    )
    if not determinism_ok:
        failures.append("Canonical rerun mismatch: output reports differed across identical seeded runs")

    # 8. Monthly sums reconcile to aggregate totals
    months = list(monthly_metrics.keys())
    sum_lines = sum(monthly_metrics[m].input_bank_lines for m in months)
    sum_credited = sum(monthly_metrics[m].total_credited_paise for m in months)
    sum_reconciled_cnt = sum(monthly_metrics[m].reconciled_credits for m in months)
    sum_reconciled_paise = sum(monthly_metrics[m].reconciled_paise for m in months)
    sum_itc = sum(monthly_metrics[m].recoverable_itc_paise for m in months)
    sum_attributed = sum(monthly_metrics[m].attributed_lines for m in months)
    sum_abstained = sum(monthly_metrics[m].abstained_lines for m in months)

    sums_match = (
        sum_lines == aggregate_metrics["n_bank_lines"]
        and sum_credited == aggregate_metrics["total_credit_paise"]
        and sum_reconciled_cnt == aggregate_metrics["reconciled_count"]
        and sum_reconciled_paise == aggregate_metrics["reconciled_paise"]
        and sum_itc == aggregate_metrics["fee_gst_recoverable_paise"]
        and sum_attributed == aggregate_metrics["attributed"]
        and sum_abstained == aggregate_metrics["abstained"]
    )
    if not sums_match:
        failures.append(
            f"Monthly metric sum mismatch: lines ({sum_lines} vs {aggregate_metrics['n_bank_lines']}), "
            f"credited ({sum_credited} vs {aggregate_metrics['total_credit_paise']}), "
            f"reconciled ({sum_reconciled_paise} vs {aggregate_metrics['reconciled_paise']}), "
            f"ITC ({sum_itc} vs {aggregate_metrics['fee_gst_recoverable_paise']})"
        )

    all_passed = (
        single_verdict
        and paise_conserved
        and no_double_covered
        and journal_balanced
        and recovery_ok
        and cert_valid
        and determinism_ok
        and sums_match
    )

    return MultiMonthInvariantResults(
        all_passed=all_passed,
        single_verdict_per_line=single_verdict,
        line_key_conservation=single_verdict,
        paise_conservation=paise_conserved,
        zero_double_covered_rows=no_double_covered,
        journal_balanced=journal_balanced,
        recovery_determinism_and_isolation=recovery_ok,
        certificate_valid=cert_valid,
        determinism_verified=determinism_ok,
        monthly_sums_reconcile_to_aggregate=sums_match,
        failures=tuple(failures),
    )


def run_multimonth_evaluation(
    dataset: BenchmarkDataset | None = None,
    *,
    seed: int = 42,
    scale: float = 0.15,
    base_epoch: int = 1_775_001_600,
    n_days: int = 91,
) -> MultiMonthEvaluationResult:
    """Execute the complete 90-day multi-month evaluation pipeline."""
    if dataset is None:
        dataset = generate_multimonth_dataset(
            seed=seed,
            scale=scale,
            base_epoch=base_epoch,
            n_days=n_days,
        )

    bank_lines = load_bank_bytes(dataset.bank_bytes)
    recon_rows = load_recon_bytes(dataset.recon_bytes)

    # Date window
    dates = [ln.value_date for ln in bank_lines]
    date_window = {
        "start_date": min(dates).isoformat() if dates else "",
        "end_date": max(dates).isoformat() if dates else "",
        "n_calendar_months": len({ln.value_date.strftime("%Y-%m") for ln in bank_lines}),
        "covered_months": sorted({ln.value_date.strftime("%Y-%m") for ln in bank_lines}),
    }

    # Run 1: Measure execution time and heap
    _TRACEMALLOC_LOCK.acquire()
    try:
        caller_tracing = tracemalloc.is_tracing()
        if not caller_tracing:
            tracemalloc.start()
        baseline_current = tracemalloc.get_traced_memory()[0]
    except BaseException:
        _TRACEMALLOC_LOCK.release()
        raise
    try:
        t0 = time.perf_counter()
        report = reconcile_bytes(
            dataset.bank_bytes, dataset.recon_bytes, dataset.ledger_bytes,
            no_ai=True, seed=dataset.seed,
        )
        t1 = time.perf_counter()
        current_raw, peak_raw = tracemalloc.get_traced_memory()
        # Attribute only growth during this evaluation.  Do not reset_peak(), since that
        # mutates a caller-owned tracing session and destroys its historical measurement.
        current_heap = max(0, current_raw - baseline_current)
        peak_heap = None if caller_tracing else peak_raw
    finally:
        if not caller_tracing:
            tracemalloc.stop()
        _TRACEMALLOC_LOCK.release()

    duration = t1 - t0

    # Run 2: Deterministic replay
    report_rerun = reconcile_bytes(
        dataset.bank_bytes,
        dataset.recon_bytes,
        dataset.ledger_bytes,
        no_ai=True,
        seed=dataset.seed,
    )

    # Certificate issuance and verification
    cert = issue_certificate(report)
    cert_verify = verify_certificate({**cert, "report": report})

    # Compute monthly metrics
    monthly_metrics, aggregate_metrics = _compute_monthly_metrics(report, bank_lines, recon_rows)

    # Invariant audit
    invariants = _audit_multimonth_invariants(
        report,
        report_rerun,
        cert_verify,
        bank_lines,
        recon_rows,
        monthly_metrics,
        aggregate_metrics,
    )

    environment = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }

    limitations = [
        "Synthetic 90-Day Evaluation: Validates mathematical conservation, multi-month attribution, and period-boundary invariants under controlled corruption.",
        "Bank Ingestion Boundary: Does not establish native export compatibility for named Indian banks without authentic specimens (see BANK_FORMAT_EVIDENCE.md).",
        "Memory Measurement Scope: tracemalloc measures Python interpreter heap allocations, not total operating system process RSS.",
    ]

    return MultiMonthEvaluationResult(
        version=MULTIMONTH_EVAL_VERSION,
        seed=dataset.seed,
        scale=dataset.scale,
        base_epoch=dataset.manifest.get("config", {}).get("base_epoch", base_epoch),
        n_days=dataset.manifest.get("config", {}).get("n_days", n_days),
        date_window=date_window,
        duration_seconds=duration,
        peak_python_heap_bytes=peak_heap,
        current_python_heap_bytes=current_heap,
        input_metrics=dataset.manifest["row_counts"],
        monthly_metrics=monthly_metrics,
        aggregate_metrics=aggregate_metrics,
        invariants=invariants,
        environment=environment,
        limitations=limitations,
    )


def format_multimonth_terminal_table(result: MultiMonthEvaluationResult) -> str:
    """Format evaluation results as a clean terminal dashboard."""
    lines: list[str] = [
        "",
        "=" * 82,
        "  UNTANGLE MULTI-MONTH & 90-DAY EVALUATION (Phase 1, Task 6)",
        "=" * 82,
        f"  Date Window         : {result.date_window['start_date']} to {result.date_window['end_date']} "
        f"({result.date_window['n_calendar_months']} calendar months)",
        f"  Covered Months      : {', '.join(result.date_window['covered_months'])}",
        f"  Seed / Scale        : {result.seed} / {result.scale}",
        f"  Platform / Python   : {result.environment['platform']} (Python {result.environment['python_version']})",
        f"  Duration / Peak Heap: {result.duration_seconds:.4f} s / "
        f"{result.peak_python_heap_bytes / (1024 * 1024):.2f} MiB (Python heap)"
        if result.peak_python_heap_bytes is not None else
        f"  Duration / Peak Heap: {result.duration_seconds:.4f} s / unavailable (caller tracing active)",
        "-" * 82,
        "  PER-MONTH RECONCILIATION BREAKDOWN:",
        "  Month    Lines  Attributed  Abstained  Razorpay  Reconciled Credits  Recoverable ITC   Total Credited",
        "  " + "-" * 78,
    ]

    for m, d in result.monthly_metrics.items():
        lines.append(
            f"  {m:<7}  {d.input_bank_lines:>5}  {d.attributed_lines:>10}  {d.abstained_lines:>9}  "
            f"{d.razorpay_lines:>8}  {d.reconciled_credits:>10} (₹{d.reconciled_paise/100:>10,.2f})  "
            f"₹{d.recoverable_itc_paise/100:>9,.2f}  ₹{d.total_credited_paise/100:>12,.2f}"
        )

    lines.append("  " + "-" * 78)
    agg = result.aggregate_metrics
    lines.append(
        f"  TOTAL    {agg['n_bank_lines']:>5}  {agg['attributed']:>10}  {agg['abstained']:>9}  "
        f"{sum(d.razorpay_lines for d in result.monthly_metrics.values()):>8}  "
        f"{agg['reconciled_count']:>10} (₹{agg['reconciled_paise']/100:>10,.2f})  "
        f"₹{agg['fee_gst_recoverable_paise']/100:>9,.2f}  ₹{agg['total_credit_paise']/100:>12,.2f}"
    )

    lines.extend([
        "-" * 82,
        "  CROSS-MONTH INVARIANT AUDIT:",
        f"    - 1:1 Line Verdict & Conservation : {'PASS' if result.invariants.single_verdict_per_line else 'FAIL'}",
        f"    - Exact Paise Conservation         : {'PASS' if result.invariants.paise_conservation else 'FAIL'}",
        f"    - Zero Double-Covered Recon Rows   : {'PASS' if result.invariants.zero_double_covered_rows else 'FAIL'}",
        f"    - Balanced Double-Entry Journal    : {'PASS' if result.invariants.journal_balanced else 'FAIL'}",
        f"    - Recovery & Debit Isolation       : {'PASS' if result.invariants.recovery_determinism_and_isolation else 'FAIL'}",
        f"    - Period Close Certificate Valid   : {'PASS' if result.invariants.certificate_valid else 'FAIL'}",
        f"    - Deterministic Replay Identity    : {'PASS' if result.invariants.determinism_verified else 'FAIL'}",
        f"    - Monthly Sums Reconcile to Total  : {'PASS' if result.invariants.monthly_sums_reconcile_to_aggregate else 'FAIL'}",
        "-" * 82,
        f"  OVERALL RESULT: [{'PASS' if result.invariants.all_passed else 'FAIL'}] "
        + ("All multi-month invariants held without error." if result.invariants.all_passed else f"Failures: {result.invariants.failures}"),
        "=" * 82,
        "",
    ])

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for multi-month evaluation."""
    parser = argparse.ArgumentParser(
        description="Untangle Extended 90-Day and Multi-Month Evaluation"
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed (default 42)")
    parser.add_argument("--scale", type=float, default=0.15, help="Scale factor (default 0.15)")
    parser.add_argument(
        "--base-epoch",
        type=int,
        default=1_775_001_600,
        help="UTC seconds start date (default 1775001600 = 2026-04-01)",
    )
    parser.add_argument("--days", type=int, default=91, help="Date range in days (default 91)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args(argv)

    result = run_multimonth_evaluation(
        seed=args.seed,
        scale=args.scale,
        base_epoch=args.base_epoch,
        n_days=args.days,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_multimonth_terminal_table(result))

    return 0 if result.invariants.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

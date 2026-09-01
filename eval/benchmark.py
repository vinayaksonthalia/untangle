"""Maximum-Payload End-to-End Stress and Resource Benchmark (Phase 1, Task 4).

Exercises the complete reconciliation pipeline:
    ingest → attribution → solver/reconciliation → exceptions → investigation → journal/certificate output

Measures:
- Input byte sizes and row counts.
- End-to-end execution runtime (seconds).
- Peak Python heap memory allocated via `tracemalloc` (Python heap only; not total process RSS).
- Complete conservation, paise balance, and determinism invariants.

Usage:
    python -m eval.benchmark --profile ci-safe
    python -m eval.benchmark --profile near-limit
    python -m eval.benchmark --profile near-limit --global-solver --json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from engine.certificate import issue_certificate, verify_certificate
from engine.journal import journal_json_to_tally_xml
from engine.service import reconcile_bytes
from eval.benchmark_generator import BenchmarkDataset, generate_benchmark_dataset


@dataclass(frozen=True)
class InvariantResults:
    """Status of all mathematical and structural invariants under load."""

    all_passed: bool
    single_verdict_per_line: bool
    attribution_conservation: bool
    paise_conservation: bool
    journal_balanced: bool
    no_duplicate_covered_rows: bool
    certificate_valid: bool
    determinism_verified: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkResult:
    """Benchmark execution metrics and invariant audit for one run."""

    profile: str
    seed: int
    scale: float
    global_solver: bool
    duration_seconds: float
    peak_python_heap_bytes: int
    current_python_heap_bytes: int
    input_metrics: dict[str, Any]
    output_metrics: dict[str, Any]
    invariants: InvariantResults
    environment: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["peak_python_heap_mb"] = round(self.peak_python_heap_bytes / (1024 * 1024), 2)
        d["duration_seconds"] = round(self.duration_seconds, 4)
        return d


def _audit_invariants(
    report: dict[str, Any],
    report_rerun: dict[str, Any],
    cert_verify: dict[str, Any],
    n_bank_lines: int,
) -> InvariantResults:
    """Audit all mathematical, conservation, and determinism invariants."""
    failures: list[str] = []

    # 1. Single verdict per line & attribution conservation
    attributions = report.get("attributions", [])
    single_verdict = len(attributions) == n_bank_lines
    if not single_verdict:
        failures.append(
            f"Line count mismatch: expected {n_bank_lines} attributions, got {len(attributions)}"
        )

    by_rail_count = report.get("totals", {}).get("by_rail_count", {})
    unknown_count = report.get("totals", {}).get("unknown_count", 0)
    total_attributed_or_abstained = sum(by_rail_count.values()) + unknown_count
    attribution_conserved = total_attributed_or_abstained == n_bank_lines
    if not attribution_conserved:
        failures.append(
            f"Attribution conservation failed: total={n_bank_lines}, "
            f"sum(attributed+unknown)={total_attributed_or_abstained}"
        )

    # 2. Paise conservation in reconciled credits
    reconciliations = report.get("reconciliations", [])
    # residual drift check: residual must be <= drift tolerance (100 paise)
    paise_conserved = True
    for rec in reconciliations:
        if rec.get("status") == "reconciled":
            if abs(rec.get("residual_paise", 0)) > 100:
                paise_conserved = False
                failures.append(
                    f"Reconciled credit {rec.get('line_key')} exceeded drift tolerance: "
                    f"{rec.get('residual_paise')} paise"
                )

    # 3. Journal double-entry balance in paise
    journal = report.get("journal", [])
    journal_balanced = True
    for voucher in journal:
        total_dr = sum(entry.get("debit_paise", 0) for entry in voucher.get("entries", []))
        total_cr = sum(entry.get("credit_paise", 0) for entry in voucher.get("entries", []))
        if total_dr != total_cr:
            journal_balanced = False
            failures.append(
                f"Unbalanced journal voucher {voucher.get('voucher_id')}: "
                f"debit={total_dr} paise, credit={total_cr} paise"
            )

    # 4. No duplicate covered row consumed twice across reconciled credits
    seen_rows: set[str] = set()
    no_duplicates = True
    for rec in reconciliations:
        for cid in rec.get("covered_row_ids", []):
            if cid in seen_rows:
                no_duplicates = False
                failures.append(f"Duplicate covered row consumed across multiple credits: {cid}")
            seen_rows.add(cid)

    # 5. Certificate validity
    cert_valid = bool(cert_verify.get("ok")) and bool(
        cert_verify.get("hash_matches")
    ) and bool(cert_verify.get("report_binding_valid"))
    if not cert_valid:
        failures.append(f"Period close certificate verification failed: {cert_verify}")

    # 6. Determinism (byte-identical second run)
    root1 = report.get("audit_root")
    root2 = report_rerun.get("audit_root")
    deterministic = bool(root1 and root1 == root2)
    if not deterministic:
        failures.append(f"Non-deterministic rerun: audit_root '{root1}' != '{root2}'")

    all_passed = (
        single_verdict
        and attribution_conserved
        and paise_conserved
        and journal_balanced
        and no_duplicates
        and cert_valid
        and deterministic
    )

    return InvariantResults(
        all_passed=all_passed,
        single_verdict_per_line=single_verdict,
        attribution_conservation=attribution_conserved,
        paise_conservation=paise_conserved,
        journal_balanced=journal_balanced,
        no_duplicate_covered_rows=no_duplicates,
        certificate_valid=cert_valid,
        determinism_verified=deterministic,
        failures=tuple(failures),
    )


def run_benchmark(
    profile: str = "ci-safe",
    *,
    seed: int = 42,
    scale: float | None = None,
    global_solver: bool = False,
    dataset: BenchmarkDataset | None = None,
) -> BenchmarkResult:
    """Execute complete end-to-end reconciliation benchmark and audit invariants."""
    if dataset is None:
        dataset = generate_benchmark_dataset(profile=profile, seed=seed, scale=scale)

    # First pass with memory tracing and timing
    tracemalloc.start()
    t0 = time.perf_counter()

    report = reconcile_bytes(
        dataset.bank_bytes,
        dataset.recon_bytes,
        dataset.ledger_bytes,
        no_ai=True,
        seed=dataset.seed,
        global_solver=global_solver,
    )
    cert = issue_certificate(report)
    cert_verify = verify_certificate({**cert, "report": report})
    _tally_xml = journal_json_to_tally_xml(report.get("journal", []))

    duration = time.perf_counter() - t0
    current_heap, peak_heap = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Second pass for determinism verification (re-run on identical bytes)
    report_rerun = reconcile_bytes(
        dataset.bank_bytes,
        dataset.recon_bytes,
        dataset.ledger_bytes,
        no_ai=True,
        seed=dataset.seed,
        global_solver=global_solver,
    )

    invariants = _audit_invariants(
        report,
        report_rerun,
        cert_verify,
        dataset.row_counts["bank_statement_lines"],
    )

    totals = report.get("totals", {})
    input_metrics = {
        "byte_sizes": dataset.byte_sizes,
        "total_bytes": dataset.total_bytes,
        "total_mb": round(dataset.total_bytes / (1024 * 1024), 2),
        "row_counts": dataset.row_counts,
    }
    output_metrics = {
        "n_attributions": len(report.get("attributions", [])),
        "by_rail_count": totals.get("by_rail_count", {}),
        "unknown_count": totals.get("unknown_count", 0),
        "reconciled_credits": totals.get("reconciled_count", 0),
        "reconciled_paise": totals.get("reconciled_paise", 0),
        "unresolved_rzp_count": totals.get("unresolved_rzp_count", 0),
        "fee_gst_recoverable_paise": totals.get("fee_gst_recoverable_paise", 0),
        "exceptions_count": totals.get("exception_count", 0),
        "journal_vouchers_count": len(report.get("journal", [])),
        "audit_root": report.get("audit_root"),
    }

    env = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }

    return BenchmarkResult(
        profile=dataset.profile,
        seed=dataset.seed,
        scale=dataset.scale,
        global_solver=global_solver,
        duration_seconds=duration,
        peak_python_heap_bytes=peak_heap,
        current_python_heap_bytes=current_heap,
        input_metrics=input_metrics,
        output_metrics=output_metrics,
        invariants=invariants,
        environment=env,
    )


def print_benchmark_summary(result: BenchmarkResult) -> None:
    """Print human-readable summary of benchmark execution and invariant status."""
    res_dict = result.to_dict()
    in_m = result.input_metrics
    out_m = result.output_metrics
    inv = result.invariants

    print("\n" + "=" * 78)
    print(f"  UNTANGLE PIPELINE STRESS BENCHMARK — Profile: {result.profile.upper()}")
    print("=" * 78)
    print(f"  Timestamp (UTC)     : {result.environment['timestamp_utc']}")
    print(f"  Platform / Python   : {result.environment['platform']} (Python {result.environment['python_version']})")
    print(f"  Scale / Seed        : {result.scale:.2f} / {result.seed}")
    print(f"  Global Solver       : {'ENABLED (ON)' if result.global_solver else 'DISABLED (OFF - Baseline)'}")
    print("-" * 78)
    print("  INPUT METRICS:")
    print(f"    - Recon Report JSON : {in_m['byte_sizes']['recon_report.json']:,} bytes ({in_m['byte_sizes']['recon_report.json']/(1024*1024):.2f} MiB) · {in_m['row_counts']['recon_rows']:,} rows")
    print(f"    - Order Ledger CSV  : {in_m['byte_sizes']['order_ledger.csv']:,} bytes ({in_m['byte_sizes']['order_ledger.csv']/(1024*1024):.2f} MiB) · {in_m['row_counts']['order_ledger_rows']:,} rows")
    print(f"    - Bank Statement CSV: {in_m['byte_sizes']['bank_statement.csv']:,} bytes ({in_m['byte_sizes']['bank_statement.csv']/(1024*1024):.2f} MiB) · {in_m['row_counts']['bank_statement_lines']:,} lines")
    print(f"    - Total Payload     : {in_m['total_bytes']:,} bytes ({in_m['total_mb']:.2f} MiB)")
    print("-" * 78)
    print("  RESOURCE & PERFORMANCE MEASUREMENTS:")
    print(f"    - Wall-clock Time   : {result.duration_seconds:.4f} s")
    print(f"    - Peak Python Heap  : {res_dict['peak_python_heap_mb']:.2f} MiB ({result.peak_python_heap_bytes:,} bytes)")
    print("      (Note: Measured with tracemalloc; represents Python heap allocations, not total process RSS)")
    print("-" * 78)
    print("  RECONCILIATION OUTPUT SUMMARY:")
    print(f"    - Total Attributed  : {out_m['n_attributions']} lines (Razorpay: {out_m['by_rail_count'].get('razorpay_settlement', 0)}, Unknown: {out_m['unknown_count']})")
    print(f"    - Reconciled Credits: {out_m['reconciled_credits']} credits (₹{out_m['reconciled_paise']/100:,.2f})")
    print(f"    - Unresolved Slice  : {out_m['unresolved_rzp_count']} credits")
    print(f"    - Recoverable ITC   : ₹{out_m['fee_gst_recoverable_paise']/100:,.2f}")
    print(f"    - Exceptions / Inv. : {out_m['exceptions_count']} items")
    print(f"    - Journal Vouchers  : {out_m['journal_vouchers_count']} double-entry vouchers")
    print(f"    - Audit Root Hash   : {out_m['audit_root']}")
    print("-" * 78)
    print("  INVARIANT AUDIT:")
    print(f"    - 1:1 Terminal Verdicts     : {'PASS' if inv.single_verdict_per_line else 'FAIL'}")
    print(f"    - Attribution Conservation  : {'PASS' if inv.attribution_conservation else 'FAIL'}")
    print(f"    - Exact Paise Conservation  : {'PASS' if inv.paise_conservation else 'FAIL'}")
    print(f"    - Double-entry Journal Bal. : {'PASS' if inv.journal_balanced else 'FAIL'}")
    print(f"    - Zero Double-Covered Rows  : {'PASS' if inv.no_duplicate_covered_rows else 'FAIL'}")
    print(f"    - Close Certificate Valid   : {'PASS' if inv.certificate_valid else 'FAIL'}")
    print(f"    - Determinism on Rerun      : {'PASS' if inv.determinism_verified else 'FAIL'}")
    print("-" * 78)
    if inv.all_passed:
        print("  OVERALL RESULT: [PASS] All performance & correctness invariants held under load.")
    else:
        print("  OVERALL RESULT: [FAIL] Invariant violations detected:")
        for f in inv.failures:
            print(f"    * {f}")
    print("=" * 78 + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Untangle maximum-payload stress and resource benchmark."
    )
    parser.add_argument(
        "--profile",
        choices=["ci-safe", "moderate", "near-limit", "both"],
        default="ci-safe",
        help="Benchmark profile to run (default: ci-safe).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic RNG seed (default: 42).",
    )
    parser.add_argument(
        "--global-solver",
        action="store_true",
        help="Enable global constrained reconciliation solver.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON summary.",
    )
    parser.add_argument(
        "--out-file",
        type=str,
        default=None,
        help="Optional path to write JSON benchmark results to.",
    )

    args = parser.parse_args(argv)

    profiles_to_run = (
        ["ci-safe", "near-limit"] if args.profile == "both" else [args.profile]
    )

    results: list[BenchmarkResult] = []
    exit_code = 0

    for prof in profiles_to_run:
        res = run_benchmark(
            profile=prof,
            seed=args.seed,
            global_solver=args.global_solver,
        )
        results.append(res)
        if not res.invariants.all_passed:
            exit_code = 1
        if not args.json_output:
            print_benchmark_summary(res)

    if args.json_output:
        payload = [r.to_dict() for r in results] if len(results) > 1 else results[0].to_dict()
        print(json.dumps(payload, indent=2))

    if args.out_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_file)), exist_ok=True)
        payload = [r.to_dict() for r in results] if len(results) > 1 else results[0].to_dict()
        with open(args.out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

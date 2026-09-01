"""Deterministic high-volume dataset generator for benchmark and stress evaluations.

Reuses generator primitives (generator.build, generator.bank, generator.noise, generator.selfcheck)
to produce deterministic, syntactically valid, and mathematically sound datasets at configurable scales
(CI-safe, moderate, near-limit, and oversized).
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from typing import Any

from generator import bank as BANK
from generator import build as B
from generator import config as C
from generator import noise as NOISE
from generator import selfcheck as SELFCHECK
from generator.generate import RECON_FIELDS, _iso, _iso_dt, _rupees

# Profile specifications
PROFILES: dict[str, dict[str, Any]] = {
    "ci-safe": {
        "scale": 0.15,
        "description": "Lightweight ~1.8k recon rows (~1.2 MiB JSON), fast CI execution (<1s).",
    },
    "moderate": {
        "scale": 0.5,
        "description": "Standard ~6k recon rows (~4.2 MiB JSON), balanced load testing (~2s).",
    },
    "near-limit": {
        "scale": 1.75,
        "description": "High-volume ~21.7k recon rows (~14.7 MiB JSON), exercises near the 15 MiB per-file limit (~8s).",
    },
}

MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MiB
MAX_AGGREGATE_BYTES = 3 * MAX_FILE_BYTES + 1024 * 1024  # 46 MiB


@dataclass(frozen=True)
class BenchmarkDataset:
    """In-memory benchmark dataset with immutable byte buffers and metadata."""

    profile: str
    seed: int
    scale: float
    bank_bytes: bytes
    recon_bytes: bytes
    ledger_bytes: bytes
    row_counts: dict[str, int]
    byte_sizes: dict[str, int]
    total_bytes: int
    manifest: dict[str, Any]

    def write_to_directory(self, target_dir: str) -> dict[str, str]:
        """Write dataset files to a directory and return a dict of file paths."""
        os.makedirs(target_dir, exist_ok=True)
        paths = {
            "bank_path": os.path.join(target_dir, "bank_statement.csv"),
            "recon_path": os.path.join(target_dir, "recon_report.json"),
            "ledger_path": os.path.join(target_dir, "order_ledger.csv"),
        }
        with open(paths["bank_path"], "wb") as f:
            f.write(self.bank_bytes)
        with open(paths["recon_path"], "wb") as f:
            f.write(self.recon_bytes)
        with open(paths["ledger_path"], "wb") as f:
            f.write(self.ledger_bytes)
        return paths


def _format_recon_json(recon_rows: list[dict]) -> bytes:
    """Format recon rows as compact, standard JSON bytes matching Razorpay export structure."""
    ordered = []
    for r in recon_rows:
        o = {k: r[k] for k in RECON_FIELDS if k in r}
        ordered.append(o)
    return json.dumps(ordered, ensure_ascii=False, indent=2).encode("utf-8")


def _format_order_ledger_csv(ledger: list[dict]) -> bytes:
    """Format order ledger rows as CSV bytes."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "order_id",
        "amount_paise",
        "gst_rate_pct",
        "gst_amount_paise",
        "status",
        "created_at",
        "receipt",
        "payment_method",
    ])
    for o in ledger:
        writer.writerow([
            o["order_id"],
            o["amount"],
            int(round(o["gst_rate"] * 100)),
            o["gst_amount"],
            o["status"],
            _iso_dt(o["created_at"]),
            o["receipt"],
            o["payment_method"],
        ])
    return buf.getvalue().encode("utf-8")


def _format_bank_statement_csv(lines: list[dict]) -> bytes:
    """Format bank statement lines as standard CSV bytes."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "line_id",
        "value_date",
        "txn_date",
        "narration",
        "ref_no",
        "debit",
        "credit",
        "balance",
    ])
    for ln in lines:
        writer.writerow([
            ln["line_id"],
            _iso(ln["value_date"]),
            _iso(ln["txn_date"]),
            ln["narration"],
            ln["ref_no"],
            _rupees(ln["debit_paise"]) if ln["debit_paise"] else "",
            _rupees(ln["credit_paise"]) if ln["credit_paise"] else "",
            _rupees(ln["_balance_paise"]),
        ])
    return buf.getvalue().encode("utf-8")


def generate_benchmark_dataset(
    profile: str = "ci-safe",
    *,
    seed: int = 42,
    scale: float | None = None,
    base_epoch: int = C.Config.base_epoch,
    n_days: int = C.Config.n_days,
) -> BenchmarkDataset:
    """Generate an in-memory benchmark dataset deterministically.

    Args:
        profile: Preset name ('ci-safe', 'moderate', 'near-limit').
        seed: Fixed random seed.
        scale: Optional explicit scale multiplier (overrides profile preset).
        base_epoch: Fixed base epoch in UTC seconds.
        n_days: Date range in days.

    Returns:
        BenchmarkDataset with immutable bank, recon, and ledger byte buffers.
    """
    if scale is None:
        if profile not in PROFILES:
            raise ValueError(
                f"Unknown benchmark profile: {profile!r}. Choose from: {sorted(PROFILES.keys())}"
            )
        scale = PROFILES[profile]["scale"]

    cfg = C.Config(
        seed=seed,
        scale=scale,
        base_epoch=base_epoch,
        n_days=n_days,
    )

    built = B.build(cfg)
    bank_lines, truth = BANK.build_bank_and_truth(cfg, built)
    ledger, ledger_counts = NOISE.corrupt_ledger(cfg, built["orders"])

    # Fail-closed conservation check on generated data
    check = SELFCHECK.run(built["recon_rows"], bank_lines, truth)
    if check["status"] != "PASS":
        raise RuntimeError(f"Benchmark dataset generation selfcheck failed: {check}")

    recon_bytes = _format_recon_json(built["recon_rows"])
    ledger_bytes = _format_order_ledger_csv(ledger)
    bank_bytes = _format_bank_statement_csv(bank_lines)

    row_counts = {
        "recon_rows": len(built["recon_rows"]),
        "order_ledger_rows": len(ledger),
        "bank_statement_lines": len(bank_lines),
        "ground_truth_labels": len(truth),
    }

    byte_sizes = {
        "recon_report.json": len(recon_bytes),
        "order_ledger.csv": len(ledger_bytes),
        "bank_statement.csv": len(bank_bytes),
    }
    total_bytes = sum(byte_sizes.values())

    manifest = {
        "generator_version": "1.0.0",
        "profile": profile,
        "config": cfg.summary(),
        "row_counts": row_counts,
        "byte_sizes": byte_sizes,
        "total_bytes": total_bytes,
        "selfcheck": check,
    }

    return BenchmarkDataset(
        profile=profile,
        seed=seed,
        scale=scale,
        bank_bytes=bank_bytes,
        recon_bytes=recon_bytes,
        ledger_bytes=ledger_bytes,
        row_counts=row_counts,
        byte_sizes=byte_sizes,
        total_bytes=total_bytes,
        manifest=manifest,
    )


def create_oversized_file(
    base_bytes: bytes,
    target_size: int = MAX_FILE_BYTES + 1,
    *,
    is_json: bool = True,
) -> bytes:
    """Pad an existing byte payload to strictly exceed a target size.

    For JSON, pads with trailing whitespace/comments so the structural payload remains intact.
    For CSV, pads with trailing commented lines or empty lines.
    """
    if len(base_bytes) >= target_size:
        return base_bytes
    pad_len = target_size - len(base_bytes)
    if is_json:
        # JSON ignores trailing spaces
        return base_bytes + (b" " * pad_len)
    # CSV ignores comment lines starting with # or trailing blank lines
    return base_bytes + (b"\n" * pad_len)


def create_oversized_aggregate_dataset(
    target_total: int = MAX_AGGREGATE_BYTES + 1,
) -> tuple[bytes, bytes, bytes]:
    """Create a 3-file payload whose total size exceeds the aggregate upload ceiling."""
    ds = generate_benchmark_dataset(profile="ci-safe", seed=42)
    # Pad the recon bytes so total exceeds target_total
    current_total = len(ds.bank_bytes) + len(ds.recon_bytes) + len(ds.ledger_bytes)
    if current_total >= target_total:
        return ds.bank_bytes, ds.recon_bytes, ds.ledger_bytes
    needed = target_total - current_total
    padded_recon = ds.recon_bytes + (b" " * needed)
    return ds.bank_bytes, padded_recon, ds.ledger_bytes

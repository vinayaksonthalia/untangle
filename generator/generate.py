"""
`untangle` synthetic-data generator — entry point.

Usage:
    python -m generator.generate --seed 42 --scale 1.0 --out data
    python -m generator.generate --seed 7 --scale 0.1 --base-epoch 1780272000

Produces, into --out (default ./data):
    recon_report.json    Razorpay settlement recon rows (verified field shape)
    order_ledger.csv     merchant order ledger (messy: missing/mangled/dup ids)
    bank_statement.csv   commingled multi-rail bank statement (the centerpiece)
    ground_truth.json    per-bank-line rail attribution + covered recon rows
    manifest.json        seed, scale, per-rail & per-hard-case counts, file hashes

Nothing here uses wall-clock time or unseeded randomness: given the same
--seed/--scale/--base-epoch the byte output is identical.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time

from . import bank as BANK
from . import build as B
from . import config as C
from . import noise as NOISE
from . import selfcheck as SELFCHECK

GENERATOR_VERSION = "1.0.0"

# Field order = frozen recon schema (fixtures/recon_sdk_node_2026-08-21.md).
RECON_FIELDS = [
    "entity_id", "type", "debit", "credit", "amount", "currency", "fee", "tax",
    "on_hold", "settled", "created_at", "settled_at", "settlement_id", "posted_at",
    "credit_type", "description", "notes", "payment_id", "settlement_utr",
    "order_id", "order_receipt", "method", "card_network", "card_issuer",
    "card_type", "dispute_id", "authorized_amount", "captured_amount",
]


def _iso(epoch) -> str:
    if epoch is None:
        return ""
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def _iso_dt(epoch) -> str:
    if epoch is None:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(epoch))


def _rupees(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    p = abs(paise)
    return f"{sign}{p // 100}.{p % 100:02d}"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_recon(path: str, rows: list[dict]) -> None:
    ordered = []
    for r in rows:
        # preserve schema order; adjustment rows legitimately omit credit_type (V10)
        o = {k: r[k] for k in RECON_FIELDS if k in r}
        ordered.append(o)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)


def _write_order_ledger(path: str, ledger: list[dict]) -> None:
    cols = ["order_id", "amount_paise", "gst_rate_pct", "gst_amount_paise",
            "status", "created_at", "receipt", "payment_method"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for o in ledger:
            w.writerow([
                o["order_id"], o["amount"], int(round(o["gst_rate"] * 100)),
                o["gst_amount"], o["status"], _iso_dt(o["created_at"]),
                o["receipt"], o["payment_method"],
            ])


def _write_bank_statement(path: str, lines: list[dict]) -> None:
    cols = ["line_id", "value_date", "txn_date", "narration", "ref_no",
            "debit", "credit", "balance"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for ln in lines:
            w.writerow([
                ln["line_id"], _iso(ln["value_date"]), _iso(ln["txn_date"]),
                ln["narration"], ln["ref_no"],
                _rupees(ln["debit_paise"]) if ln["debit_paise"] else "",
                _rupees(ln["credit_paise"]) if ln["credit_paise"] else "",
                _rupees(ln["_balance_paise"]),
            ])


def _write_truth(path: str, truth: list[dict], cfg: C.Config) -> None:
    payload = {
        "_meta": {
            "generator_version": GENERATOR_VERSION,
            "seed": cfg.seed, "scale": cfg.scale,
            "note": "Answer key. Amounts in PAISE. Join bank lines by line_id. "
                    "covered_recon_keys are [type, entity_id] pairs; key recon rows "
                    "on (type, entity_id), never payment_id (verified V3).",
        },
        "labels": truth,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def run(cfg: C.Config, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)

    built = B.build(cfg)
    bank_lines, truth = BANK.build_bank_and_truth(cfg, built)
    ledger, ledger_counts = NOISE.corrupt_ledger(cfg, built["orders"])

    # ---- fail-closed conservation check BEFORE writing anything ----
    check = SELFCHECK.run(built["recon_rows"], bank_lines, truth)

    recon_path = os.path.join(out_dir, "recon_report.json")
    ledger_path = os.path.join(out_dir, "order_ledger.csv")
    bank_path = os.path.join(out_dir, "bank_statement.csv")
    truth_path = os.path.join(out_dir, "ground_truth.json")
    manifest_path = os.path.join(out_dir, "manifest.json")

    _write_recon(recon_path, built["recon_rows"])
    _write_order_ledger(ledger_path, ledger)
    _write_bank_statement(bank_path, bank_lines)
    _write_truth(truth_path, truth, cfg)

    # ---- counts ----
    rail_counts: dict[str, int] = {}
    for t in truth:
        rail_counts[t["rail"]] = rail_counts.get(t["rail"], 0) + 1

    type_counts: dict[str, int] = {}
    for r in built["recon_rows"]:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1

    hard_counts = dict(built["_hard_counts"])
    hard_counts.update({
        "on_hold_rows": len(built["on_hold_ids"]),
        "dispute_rows": len(built["dispute_ids"]),
        "fee_variance_rows": len(built["fee_variance_ids"]),
        "cross_cycle_refunds": len(built["cross_cycle_refund_ids"]),
        "route_transfers": type_counts.get("transfer", 0),
        "adjustments": type_counts.get("adjustment", 0),
        **{f"ledger_{k}": v for k, v in ledger_counts.items()},
    })

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "config": cfg.summary(),
        "outputs": {},
        "row_counts": {
            "recon_rows": len(built["recon_rows"]),
            "recon_rows_by_type": type_counts,
            "order_ledger_rows": len(ledger),
            "bank_statement_lines": len(bank_lines),
            "ground_truth_labels": len(truth),
        },
        "per_rail_counts": rail_counts,
        "per_hard_case_counts": hard_counts,
        "selfcheck": check,
        "schema_provenance": "fixtures/recon_sdk_node_2026-08-21.md (verified field shape)",
    }
    for name, path in [
        ("recon_report.json", recon_path),
        ("order_ledger.csv", ledger_path),
        ("bank_statement.csv", bank_path),
        ("ground_truth.json", truth_path),
    ]:
        manifest["outputs"][name] = {
            "bytes": os.path.getsize(path),
            "sha256": _sha256_file(path),
        }

    # Deliberately inconsistent bank/report pairs live in a companion benchmark so the established
    # attribution dataset and all of its metrics remain byte-for-byte unchanged.
    from .investigation_cases import write_investigation_benchmark
    manifest["investigation_benchmark"] = write_investigation_benchmark(out_dir, cfg)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest


def parse_args(argv=None) -> C.Config:
    ap = argparse.ArgumentParser(description="untangle synthetic-data generator")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="1.0 -> ~12k recon rows; scale the volume linearly")
    ap.add_argument("--base-epoch", type=int, default=C.Config.base_epoch,
                    help="UTC seconds base for all derived timestamps (no wall clock)")
    ap.add_argument("--days", type=int, default=C.Config.n_days)
    ap.add_argument("--out", type=str, default="data")
    args = ap.parse_args(argv)
    cfg = C.Config(seed=args.seed, scale=args.scale,
                   base_epoch=args.base_epoch, n_days=args.days)
    cfg._out = args.out  # type: ignore[attr-defined]
    return cfg


def main(argv=None) -> None:
    cfg = parse_args(argv)
    out_dir = getattr(cfg, "_out", "data")
    manifest = run(cfg, out_dir)
    rc = manifest["row_counts"]
    print(f"[untangle] seed={cfg.seed} scale={cfg.scale} -> {out_dir}/")
    print(f"  recon rows        : {rc['recon_rows']}  {rc['recon_rows_by_type']}")
    print(f"  order ledger rows : {rc['order_ledger_rows']}")
    print(f"  bank lines        : {rc['bank_statement_lines']}")
    print(f"  per-rail counts   : {manifest['per_rail_counts']}")
    print(f"  per-hard-case     : {manifest['per_hard_case_counts']}")
    print(f"  selfcheck         : {manifest['selfcheck']['status']} "
          f"({manifest['selfcheck']['razorpay_lines_checked']} rzp lines, "
          f"{manifest['selfcheck']['settled_rows_covered']} settled rows covered)")


if __name__ == "__main__":
    main()

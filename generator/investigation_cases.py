"""Deterministic companion benchmark for root-cause investigation.

Unlike the core attribution benchmark, these cases deliberately model timing or booking
differences between a provider report and the bank. Every delta is labelled and backed by
explicit report evidence. The ambiguous control has no closing evidence and must abstain.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime

from .config import Config

ROOT_CAUSES = (
    "mdr_fee_drift",
    "cross_cycle_refund_lag",
    "on_hold_release",
    "dispute_deduction",
    "partial_capture",
    "rolling_reserve",
)


def _token(seed: int, label: str, n: int = 12) -> str:
    return hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()[:n]


def build_investigation_cases(cfg: Config) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    rows: list[dict] = []
    bank: list[dict] = []
    truth: list[dict] = []
    ledger: list[dict] = []
    base = cfg.base_epoch + 40 * 86_400

    def add_case(cause: str, evidence_rows: list[dict], delta: int) -> None:
        i = len(bank)
        sid = f"setl_inv_{_token(cfg.seed, cause)}"
        utr = f"{base + i * 86400}{_token(cfg.seed, cause + ':utr', 6)}"
        settled_at = base + i * 86_400 + 12 * 3600
        keys = []
        for j, spec in enumerate(evidence_rows):
            eid = spec.pop("entity_id", f"inv_{cause}_{j}_{_token(cfg.seed, cause + str(j), 6)}")
            row = {
                "entity_id": eid,
                "type": spec.pop("type", "payment"),
                "debit": 0,
                "credit": 0,
                "amount": 0,
                "currency": "INR",
                "fee": 0,
                "tax": 0,
                "on_hold": False,
                "settled": True,
                "created_at": settled_at,
                "settled_at": settled_at,
                "settlement_id": sid,
                "posted_at": None,
                "credit_type": "default",
                "description": None,
                "notes": None,
                "payment_id": None,
                "settlement_utr": utr,
                "order_id": None,
                "order_receipt": None,
                "method": None,
                "card_network": None,
                "card_issuer": None,
                "card_type": None,
                "dispute_id": None,
                **spec,
            }
            rows.append(row)
            keys.append([row["type"], eid])
            if row["type"] == "payment":
                oid = (
                    row.get("order_id")
                    or f"order_inv_{_token(cfg.seed, cause + ':order' + str(j))}"
                )
                row["order_id"] = oid
                ledger.append(
                    {
                        "order_id": oid,
                        "amount": row["amount"],
                        "gst_rate": 0.18,
                        "gst_amount": 0,
                        "status": "paid",
                        "created_at": row["created_at"],
                        "receipt": f"inv-{cause}-{j}",
                        "payment_method": row.get("method") or "card",
                    }
                )
        expected = sum(r["credit"] - r["debit"] for r in rows if r["settlement_id"] == sid)
        amount = expected + delta
        if amount <= 0:
            raise AssertionError(f"investigation case {cause} must remain a positive bank credit")
        lid = f"bl_inv_{_token(cfg.seed, cause)}"
        dt = datetime.fromtimestamp(settled_at, tz=UTC)
        bank.append(
            {
                "line_id": lid,
                "value_date": settled_at,
                "txn_date": settled_at,
                "narration": f"RAZORPAY SETTLEMENT {utr}",
                "ref_no": utr,
                "debit_paise": 0,
                "credit_paise": amount,
                "_balance_paise": amount,
            }
        )
        truth.append(
            {
                "line_id": lid,
                "rail": "razorpay_settlement",
                "true_amount_paise": amount,
                "report_expected_net_paise": expected,
                "bank_evidence_amount_paise": amount,
                "rounding_drift_paise": 0,
                "settlement_ids": [sid],
                "settlement_utrs": [utr],
                "covered_recon_keys": keys,
                "hard_cases": ["investigation_exception", cause],
                "intended_root_cause": cause,
                "expected_variance_paise": delta,
                "event_date": dt.date().isoformat(),
            }
        )

    add_case(
        "mdr_fee_drift",
        [{"amount": 100_000, "credit": 97_640, "fee": 2_360, "tax": 360, "method": "card"}],
        -360,
    )
    add_case(
        "cross_cycle_refund_lag",
        [
            {"amount": 120_000, "credit": 120_000, "method": "card"},
            {
                "type": "refund",
                "amount": 12_000,
                "debit": 12_000,
                "created_at": base - 2 * 86_400,
                "description": "Cross-cycle customer refund",
            },
        ],
        -12_000,
    )
    add_case(
        "on_hold_release",
        [
            {"amount": 150_000, "credit": 150_000, "method": "card"},
            {"amount": 20_000, "credit": 20_000, "on_hold": True, "method": "card"},
        ],
        -20_000,
    )
    add_case(
        "dispute_deduction",
        [
            {"amount": 180_000, "credit": 180_000, "method": "card"},
            {
                "type": "refund",
                "amount": 15_000,
                "debit": 15_000,
                "dispute_id": f"disp_inv_{_token(cfg.seed, 'dispute')}",
                "description": "Chargeback debit",
            },
        ],
        -15_000,
    )
    add_case(
        "partial_capture",
        [
            {
                "amount": 100_000,
                "credit": 100_000,
                "method": "card",
                "authorized_amount": 100_000,
                "captured_amount": 72_000,
            }
        ],
        -28_000,
    )
    add_case(
        "rolling_reserve",
        [
            {"amount": 200_000, "credit": 200_000, "method": "card"},
            {
                "type": "adjustment",
                "amount": 25_000,
                "debit": 25_000,
                "description": "Explicit rolling reserve withheld",
            },
        ],
        -25_000,
    )
    add_case("unexplained", [{"amount": 130_000, "credit": 130_000, "method": "upi"}], -12_345)
    return rows, bank, truth, ledger


def write_investigation_benchmark(out_dir: str, cfg: Config) -> dict:
    rows, bank, truth, ledger = build_investigation_cases(cfg)
    target = os.path.join(out_dir, "investigation")
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, "recon_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    with open(os.path.join(target, "bank_statement.csv"), "w", newline="", encoding="utf-8") as fh:
        cols = [
            "line_id",
            "value_date",
            "txn_date",
            "narration",
            "ref_no",
            "debit",
            "credit",
            "balance",
        ]
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for line in bank:

            def money(v: int) -> str:
                return f"{v // 100}.{v % 100:02d}" if v else ""

            writer.writerow(
                {
                    "line_id": line["line_id"],
                    "value_date": datetime.fromtimestamp(line["value_date"], tz=UTC)
                    .date()
                    .isoformat(),
                    "txn_date": datetime.fromtimestamp(line["txn_date"], tz=UTC).date().isoformat(),
                    "narration": line["narration"],
                    "ref_no": line["ref_no"],
                    "debit": money(line["debit_paise"]),
                    "credit": money(line["credit_paise"]),
                    "balance": money(line["_balance_paise"]),
                }
            )
    with open(os.path.join(target, "order_ledger.csv"), "w", newline="", encoding="utf-8") as fh:
        cols = [
            "order_id",
            "amount_paise",
            "gst_rate_pct",
            "gst_amount_paise",
            "status",
            "created_at",
            "receipt",
            "payment_method",
        ]
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for item in ledger:
            writer.writerow(
                {
                    "order_id": item["order_id"],
                    "amount_paise": item["amount"],
                    "gst_rate_pct": 18,
                    "gst_amount_paise": 0,
                    "status": item["status"],
                    "created_at": datetime.fromtimestamp(item["created_at"], tz=UTC).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "receipt": item["receipt"],
                    "payment_method": item["payment_method"],
                }
            )
    payload = {
        "_meta": {"seed": cfg.seed, "scale": cfg.scale, "benchmark": "investigation"},
        "labels": truth,
    }
    with open(os.path.join(target, "ground_truth.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return {"directory": "investigation", "cases": len(truth), "root_causes": list(ROOT_CAUSES)}

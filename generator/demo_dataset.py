"""One coherent demo dataset for the hosted `/try-sample` run.

The problem this solves: the dashboard and the investigation screen must describe the
*same* run. So the demo is a single reconcile over one dataset that is deliberately rich
on both axes:

  * **Cleanly-reconciling settlements** (``delta == 0``) — UTR-tied Razorpay settlements
    whose bank credit equals the settlement net to the paise. These give the dashboard
    real reconciled value, attribution coverage, and recoverable fee-GST, and they never
    raise an investigation (there is no variance to explain).
  * **The root-cause investigation cases** — reused verbatim from
    ``generator.investigation_cases`` (one settlement per labelled root cause plus one
    genuinely ambiguous control the engine abstains on). These drive the Investigate queue.

Everything is deterministic (seeded), synthetic, and safe to expose; nothing is persisted.
IDs are namespaced (``setl_demo_*`` / ``setl_inv_*``) and every settlement is bound by a
distinct UTR, so attribution is UTR-tied and the clean and exception settlements can never
cross-match each other.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime

from .config import Config
from .investigation_cases import build_investigation_cases

# A recon row carries every field engine.ingest may read; unused ones stay at their zero value.
_ROW_TEMPLATE: dict = {
    "debit": 0,
    "credit": 0,
    "amount": 0,
    "currency": "INR",
    "fee": 0,
    "tax": 0,
    "on_hold": False,
    "settled": True,
    "posted_at": None,
    "credit_type": "default",
    "description": None,
    "notes": None,
    "payment_id": None,
    "order_id": None,
    "order_receipt": None,
    "method": None,
    "card_network": None,
    "card_issuer": None,
    "card_type": None,
    "dispute_id": None,
}


def _token(seed: int, label: str, n: int = 12) -> str:
    return hashlib.sha256(f"demo:{seed}:{label}".encode()).hexdigest()[:n]


# Clean, cleanly-reconciling settlements. Each entry is a settlement made of one or more
# captured payments; `payments` are (gross_paise, fee_paise, tax_paise) with tax already
# inside fee. The bank credit is the exact net, so residual is 0 and no investigation opens.
# Amounts are distinct from every investigation-case net so nothing collides on amount.
_CLEAN_SETTLEMENTS: list[tuple[str, list[tuple[int, int, int]]]] = [
    ("card_batch_a", [(482_000, 11_328, 1_728)]),
    ("upi_batch_a", [(365_500, 4_386, 669)]),
    ("card_split_a", [(214_000, 5_029, 767), (168_500, 3_960, 604)]),  # two-payment settlement
    ("netbanking_a", [(529_900, 12_452, 1_900)]),
    ("card_batch_b", [(298_750, 7_021, 1_071)]),
    ("upi_split_a", [(142_300, 1_708, 261), (96_400, 1_157, 176), (75_050, 901, 137)]),  # three-payment
    ("card_batch_c", [(611_200, 14_363, 2_191)]),
    ("card_batch_d", [(157_800, 3_708, 566)]),
]


def build_demo_dataset(cfg: Config) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (recon_rows, bank_lines, ledger_rows) for the combined demo reconcile."""
    inv_rows, inv_bank, _truth, inv_ledger = build_investigation_cases(cfg)

    rows: list[dict] = list(inv_rows)
    bank: list[dict] = list(inv_bank)
    ledger: list[dict] = list(inv_ledger)

    # Clean settlements are dated after the investigation window so the two never share a day.
    base = cfg.base_epoch + 80 * 86_400

    for i, (label, payments) in enumerate(_CLEAN_SETTLEMENTS):
        sid = f"setl_demo_{_token(cfg.seed, label)}"
        utr = f"{base + i * 86_400}{_token(cfg.seed, label + ':utr', 6)}"
        settled_at = base + i * 86_400 + 12 * 3_600
        net = 0
        for j, (gross, fee, tax) in enumerate(payments):
            credit = gross - fee
            net += credit
            eid = f"pay_demo_{label}_{j}_{_token(cfg.seed, label + str(j), 6)}"
            oid = f"order_demo_{_token(cfg.seed, label + ':order' + str(j))}"
            row = dict(_ROW_TEMPLATE)
            row.update(
                {
                    "entity_id": eid,
                    "type": "payment",
                    "amount": gross,
                    "fee": fee,
                    "tax": tax,
                    "credit": credit,
                    "debit": 0,
                    "created_at": settled_at,
                    "settled_at": settled_at,
                    "settlement_id": sid,
                    "settlement_utr": utr,
                    "order_id": oid,
                    "method": "upi" if "upi" in label else "card",
                }
            )
            rows.append(row)
            ledger.append(
                {
                    "order_id": oid,
                    "amount": gross,
                    "gst_rate": 0.18,
                    "gst_amount": tax,
                    "status": "paid",
                    "created_at": settled_at,
                    "receipt": f"demo-{label}-{j}",
                    "payment_method": "upi" if "upi" in label else "card",
                }
            )
        bank.append(
            {
                "line_id": f"bl_demo_{_token(cfg.seed, label)}",
                "value_date": settled_at,
                "txn_date": settled_at,
                "narration": f"RAZORPAY SETTLEMENT {utr}",
                "ref_no": utr,
                "debit_paise": 0,
                "credit_paise": net,  # delta == 0: exact net, reconciles to the paise
                "_balance_paise": net,
            }
        )

    return rows, bank, ledger


def write_demo_dataset(out_dir: str, cfg: Config) -> str:
    """Write the demo dataset's three files under ``out_dir/demo`` and return that path."""
    rows, bank, ledger = build_demo_dataset(cfg)
    target = os.path.join(out_dir, "demo")
    os.makedirs(target, exist_ok=True)

    with open(os.path.join(target, "recon_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)

    with open(os.path.join(target, "bank_statement.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["line_id", "value_date", "txn_date", "narration", "ref_no", "debit", "credit", "balance"]
        )
        writer.writeheader()

        def money(v: int) -> str:
            return f"{v // 100}.{v % 100:02d}" if v else ""

        for line in bank:
            writer.writerow(
                {
                    "line_id": line["line_id"],
                    "value_date": datetime.fromtimestamp(line["value_date"], tz=UTC).date().isoformat(),
                    "txn_date": datetime.fromtimestamp(line["txn_date"], tz=UTC).date().isoformat(),
                    "narration": line["narration"],
                    "ref_no": line["ref_no"],
                    "debit": money(line["debit_paise"]),
                    "credit": money(line["credit_paise"]),
                    "balance": money(line["_balance_paise"]),
                }
            )

    with open(os.path.join(target, "order_ledger.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "order_id", "amount_paise", "gst_rate_pct", "gst_amount_paise",
                "status", "created_at", "receipt", "payment_method",
            ],
        )
        writer.writeheader()
        for row in ledger:
            writer.writerow(
                {
                    "order_id": row["order_id"],
                    "amount_paise": row["amount"],
                    "gst_rate_pct": 18,
                    "gst_amount_paise": row.get("gst_amount", 0),
                    "status": row["status"],
                    "created_at": datetime.fromtimestamp(row["created_at"], tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    "receipt": row["receipt"],
                    "payment_method": row["payment_method"],
                }
            )

    return target

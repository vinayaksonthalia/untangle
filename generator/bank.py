"""
Bank-statement builder — THE CENTERPIECE.

Consumes the settlement batches from build.py and emits a COMMINGLED,
MULTI-RAIL bank statement plus the GROUND-TRUTH label file. Only SOME credit
lines are Razorpay settlements; the rest are other rails that have nothing to
do with Razorpay (taxonomy B2). Every hard case from the taxonomy is injected
here, at rates taken from config.NoiseRates.

Bank statements are denominated in RUPEES with 2 decimals (not paise) — a real
merchant friction the matcher must handle. Ground truth is always in PAISE.

Ground-truth conservation contract (asserted by selfcheck.py):
  For every line with rail == "razorpay_settlement":
     true_amount_paise == Σ over covered_recon rows of (credit - debit)
  The bank's displayed credit may differ from true_amount_paise ONLY by the
  labeled `rounding_drift_paise` (taxonomy M4). Nothing else may differ.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import config as C
from .rng import Rng
from . import narration as N

DAY = 86_400


def _paise_to_rupees(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    p = abs(paise)
    return f"{sign}{p // 100}.{p % 100:02d}"


def _net_of_rows(row_index: dict, rows: List[List[str]]) -> int:
    net = 0
    for (t, eid) in rows:
        r = row_index[(t, eid)]
        net += r["credit"] - r["debit"]
    return net


def build_bank_and_truth(cfg: C.Config, built: dict) -> Tuple[List[dict], List[dict]]:
    row_index = built["row_index"]

    rng_hard = Rng(cfg.seed, "bank_hardcase")
    rng_rail = Rng(cfg.seed, "bank_rail")
    rng_utr = Rng(cfg.seed, "bank_utr")
    rng_narr = Rng(cfg.seed, "bank_narr")
    rng_line = Rng(cfg.seed, "bank_lineid")

    nr = cfg.noise

    # ---- Roll-forward pass: a settlement whose net <= 0 (refund/dispute-heavy)
    # never lands as a bank credit; Razorpay carries it into the next positive
    # settlement. We model that so EVERY settled recon row is covered by exactly
    # one bank line, and tag the carry so it is labeled/counted honestly. ----
    ordered = sorted([b for b in built["batches"] if b["rows"]],
                     key=lambda b: (b["settled_at"], b["settlement_id"]))
    eff: List[dict] = []
    carry_rows: List[List[str]] = []
    carry_ids: List[str] = []
    carry_utrs: List[str] = []
    carry_count = 0
    for b in ordered:
        rows = carry_rows + list(b["rows"])
        sids = carry_ids + [b["settlement_id"]]
        sutrs = carry_utrs + [b["settlement_utr"]]
        if _net_of_rows(row_index, rows) > 0:
            eff.append({
                "settlement_ids": sids, "settlement_utrs": sutrs, "rows": rows,
                "day": b["day"], "settled_at": b["settled_at"],
                "carried": bool(carry_rows),
            })
            if carry_rows:
                carry_count += 1
            carry_rows, carry_ids, carry_utrs = [], [], []
        else:
            carry_rows, carry_ids, carry_utrs = rows, sids, sutrs
    if carry_rows and eff:  # leftover negative tail folds into last positive line
        eff[-1]["rows"] += carry_rows
        eff[-1]["settlement_ids"] += carry_ids
        eff[-1]["settlement_utrs"] += carry_utrs
        eff[-1]["carried"] = True
        carry_count += 1

    # ---- Decide merges: pair up same-day effective settlements ----
    merged_pairs: List[Tuple[dict, dict]] = []
    used = set()
    by_day: Dict[int, List[dict]] = {}
    for b in eff:
        by_day.setdefault(b["day"], []).append(b)
    for day, day_batches in by_day.items():
        i = 0
        while i + 1 < len(day_batches):
            b1, b2 = day_batches[i], day_batches[i + 1]
            if rng_hard.chance(nr.merge_settlement_rate):
                merged_pairs.append((b1, b2))
                used.add(id(b1))
                used.add(id(b2))
                i += 2
            else:
                i += 1

    # ---- Assemble "settlement events": each becomes 1 or 2 bank lines ----
    events: List[dict] = []
    for (b1, b2) in merged_pairs:
        events.append({
            "kind": "merge",
            "settlement_ids": b1["settlement_ids"] + b2["settlement_ids"],
            "settlement_utrs": b1["settlement_utrs"] + b2["settlement_utrs"],
            "rows": b1["rows"] + b2["rows"],
            "day": b1["day"], "settled_at": b1["settled_at"],
            "carried": b1.get("carried") or b2.get("carried"),
        })
    for b in eff:
        if id(b) in used:
            continue
        events.append({
            "kind": "single",
            "settlement_ids": b["settlement_ids"],
            "settlement_utrs": b["settlement_utrs"],
            "rows": list(b["rows"]),
            "day": b["day"], "settled_at": b["settled_at"],
            "carried": b.get("carried", False),
        })

    # ---- Turn events into razorpay bank lines (with split/drift/mangling) ----
    rzp_lines: List[dict] = []
    truth: List[dict] = []
    hard_counts = {
        "split_settlement": 0, "merge_settlements": len(merged_pairs),
        "rounding_drift": 0, "mangled_utr": 0, "bank_charge": 0,
        "carry_forward": carry_count,
    }

    def emit_rzp_line(settlement_ids, settlement_utrs, rows, settled_at, day, tags):
        true_amt = _net_of_rows(row_index, rows)
        drift = 0
        if rng_hard.chance(nr.rounding_drift_rate):
            drift = rng_hard.choice([-7, -5, -3, -2, -1, 1, 2, 3, 5, 7])
            tags = tags + ["rounding_drift"]
            hard_counts["rounding_drift"] += 1
        display_paise = true_amt + drift

        utr = settlement_utrs[0]
        mangled = False
        if rng_hard.chance(nr.mangled_utr_rate):
            narr_utr = N.mangle_utr(utr, rng_utr)
            mangled = True
            tags = tags + ["mangled_utr"]
            hard_counts["mangled_utr"] += 1
        else:
            narr_utr = utr
        narration = N.razorpay_narration(narr_utr, rng_narr)

        line_id = "bl_" + rng_line.token(12)
        value_date = settled_at
        line = {
            "line_id": line_id,
            "value_date": value_date,
            "txn_date": value_date,
            "narration": narration,
            "ref_no": narr_utr,
            "credit_paise": display_paise,
            "debit_paise": 0,
            "_rail": "razorpay_settlement",
        }
        rzp_lines.append(line)
        truth.append({
            "line_id": line_id,
            "rail": "razorpay_settlement",
            "hard_cases": tags,
            "settlement_ids": settlement_ids,
            "settlement_utrs": settlement_utrs,
            "narration_utr": narr_utr,
            "utr_mangled": mangled,
            "rounding_drift_paise": drift,
            "true_amount_paise": true_amt,
            "bank_display_paise": display_paise,
            "covered_recon_keys": [[t, e] for (t, e) in rows],
        })
        return line

    for ev in events:
        base_tags = ["merge_settlements"] if ev["kind"] == "merge" else []
        if ev.get("carried"):
            base_tags = base_tags + ["carry_forward"]
        do_split = ev["kind"] == "single" and len(ev["rows"]) >= 4 and rng_hard.chance(nr.split_settlement_rate)
        if do_split:
            hard_counts["split_settlement"] += 1
            rows = list(ev["rows"])
            rng_hard.shuffle(rows)
            cut = len(rows) // 2
            groups = [rows[:cut], rows[cut:]]
            for leg, grp in enumerate(groups):
                # ensure each leg is a positive credit; if not, fold into other leg
                if _net_of_rows(row_index, grp) <= 0:
                    do_split = False
                    break
            if do_split:
                for leg, grp in enumerate(groups):
                    settled_at = ev["settled_at"] + (leg * DAY)  # different value-dates
                    emit_rzp_line(ev["settlement_ids"], ev["settlement_utrs"], grp,
                                  settled_at, ev["day"] + leg,
                                  base_tags + ["split_settlement", f"split_leg_{leg+1}of2"])
                continue
            else:
                hard_counts["split_settlement"] -= 1
        emit_rzp_line(ev["settlement_ids"], ev["settlement_utrs"], ev["rows"],
                      ev["settled_at"], ev["day"], list(base_tags))

    # ---- Non-razorpay commingled lines, interleaved by block ratio ----
    other_lines: List[dict] = []

    def emit_other(rail: str, day: int, hour: int, credit_paise: int,
                   debit_paise: int, narration: str, ref: str, hard=None):
        line_id = "bl_" + rng_line.token(12)
        vd = cfg.base_epoch + day * DAY + hour * 3600
        line = {
            "line_id": line_id, "value_date": vd, "txn_date": vd,
            "narration": narration, "ref_no": ref,
            "credit_paise": credit_paise, "debit_paise": debit_paise,
            "_rail": rail,
        }
        other_lines.append(line)
        truth.append({
            "line_id": line_id, "rail": rail,
            "hard_cases": hard or [],
            "settlement_ids": [], "settlement_utrs": [],
            "narration_utr": None, "utr_mangled": False,
            "rounding_drift_paise": 0,
            "true_amount_paise": credit_paise - debit_paise,
            "bank_display_paise": credit_paise - debit_paise,
            "covered_recon_keys": [],
        })
        return line

    n_rzp = len(rzp_lines)
    blocks = max(1, n_rzp // C.RAIL_BLOCK_RAZORPAY)
    for _ in range(blocks):
        for _ in range(C.RAIL_BLOCK_OTHER_GATEWAY):
            amt = rng_rail.randint(50000, 8000000)
            narr, ref = N.other_gateway_narration(rng_narr)
            emit_other("other_gateway", rng_rail.randint(2, cfg.n_days - 1),
                       rng_rail.randint(8, 19), amt, 0, narr, ref)
        for _ in range(C.RAIL_BLOCK_DIRECT_UPI):
            amt = rng_rail.randint(20000, 4000000)
            narr, ref = N.direct_upi_narration(rng_narr)
            emit_other("direct_upi", rng_rail.randint(2, cfg.n_days - 1),
                       rng_rail.randint(0, 23), amt, 0, narr, ref)
        for _ in range(C.RAIL_BLOCK_COD):
            amt = rng_rail.randint(100000, 6000000)
            narr, ref = N.cod_narration(rng_narr)
            emit_other("cod_remittance", rng_rail.randint(2, cfg.n_days - 1),
                       rng_rail.randint(8, 20), amt, 0, narr, ref)
        for _ in range(C.RAIL_BLOCK_UNRELATED):
            narr, ref, credit, debit = N.unrelated_narration(rng_narr, rng_rail)
            emit_other("unrelated", rng_rail.randint(2, cfg.n_days - 1),
                       rng_rail.randint(0, 23), credit, debit, narr, ref)

    # ---- Bank charge / reversal debit lines (B4), ~ per week ----
    n_weeks = max(1, cfg.n_days // 7)
    n_charges = int(round(nr.bank_charge_per_week * n_weeks))
    for _ in range(n_charges):
        chg = rng_rail.choice([1180, 2360, 590, 2950])  # incl 18% GST
        narr, ref = N.bank_charge_narration(rng_narr)
        emit_other("unrelated", rng_rail.randint(2, cfg.n_days - 1),
                   rng_rail.randint(8, 18), 0, chg, narr, ref, hard=["bank_charge"])
        hard_counts["bank_charge"] += 1

    # ---- Merge, sort chronologically, compute running balance ----
    all_lines = rzp_lines + other_lines
    all_lines.sort(key=lambda l: (l["value_date"], l["line_id"]))
    balance = 500000  # opening balance Rs.5000.00 (paise)
    for l in all_lines:
        balance += l["credit_paise"] - l["debit_paise"]
        l["_balance_paise"] = balance

    built["_hard_counts"] = hard_counts
    return all_lines, truth

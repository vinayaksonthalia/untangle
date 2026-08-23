"""
Core builder: produces the merchant ORDER LEDGER, the Razorpay RECON REPORT
rows, and the SETTLEMENT BATCHES they roll up into.

This module produces CLEAN, internally-consistent data. All messiness
(commingling, mangled UTRs, ledger export corruption) is added afterwards by
noise.py / bank.py so the corruption logic stays isolated and auditable.

Schema is the frozen recon-row shape verified against
fixtures/recon_sdk_node_2026-08-21.md. Key verified facts honored here:
  * payment rows: payment_id is NULL, the pay_* id is in entity_id (V3).
  * fee INCLUDES tax (18% GST on fee); credit(payment) = amount - fee (V4).
  * transfer rows: debit = amount + fee, order_id NULL, method/card_* NULL (V2).
  * adjustment rows: order_id/payment_id/settlement_utr NULL, credit_type OMITTED (V1/V10).
  * method enum is Indian {card, netbanking, wallet, upi, emi}; card_* NULL for non-card.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import config as C
from . import ids
from .rng import Rng

DAY = 86_400
CURRENCY = "INR"

PAYMENT_DESCRIPTIONS = [
    "Purchase Shoes", "Recurring Payment via Subscription", "Order Checkout",
    "Cart Payment", "Online Store Order", "Service Booking", None,
]


# --------------------------------------------------------------------------
# Fee model (verified V4: tax is 18% GST on fee, included WITHIN fee).
# --------------------------------------------------------------------------
def _modal_rate(method: str, network: Optional[str], ctype: Optional[str]) -> float:
    if method in ("card", "emi"):
        if method == "emi":
            return C.MODAL_RATE_EMI
        return C.MODAL_RATE_CARD.get((network, ctype), 0.02)
    if method == "netbanking":
        return C.MODAL_RATE_NETBANKING
    if method == "wallet":
        return C.MODAL_RATE_WALLET
    return C.MODAL_RATE_UPI  # upi -> 0


def compute_fee(amount: int, method: str, network, ctype, deviate: bool,
                direction_up: bool = True) -> Dict[str, int]:
    """Return {base_fee, tax, fee}. tax is inside fee. UPI stays zero even if
    a deviation was requested (PROJECT_SPEC 4b: never manufacture UPI variance).

    `direction_up` is drawn from the seeded RNG by the caller (NOT from amount
    parity): a deviating row's rate is pushed UP (x1.6) or DOWN (x0.5) at random,
    so fee-variance direction is ~50/50 rather than ~90% one-directional."""
    rate = _modal_rate(method, network, ctype)
    if deviate and method != "upi":
        # push off the cluster mode by a visible but plausible factor
        rate = rate * (1.6 if direction_up else 0.5)
    base_fee = int(round(amount * rate))
    tax = int(round(base_fee * C.GST_ON_FEE_RATE))
    fee = base_fee + tax
    return {"base_fee": base_fee, "tax": tax, "fee": fee}


def _card_fields(rng: Rng, method: str):
    """card_network / card_type / card_issuer. NULL for non-card methods
    (verified: fixture transfer/adjustment rows and Indian non-card rows)."""
    if method in ("card", "emi"):
        network = rng.weighted_choice(C.CARD_NETWORKS, [0.35, 0.34, 0.18, 0.08, 0.05])
        ctype = rng.weighted_choice(C.CARD_TYPES, [0.55, 0.45]) if method == "card" else "credit"
        issuer = rng.choice(C.CARD_ISSUERS)
        return network, ctype, issuer
    return None, None, None


def _amount(rng: Rng) -> int:
    """Order/payment gross amount in paise. Log-ish spread, Rs.49 .. Rs.75000."""
    buckets = [(4900, 49900), (49900, 199900), (199900, 999900), (999900, 7500000)]
    lo, hi = rng.weighted_choice(buckets, [0.45, 0.35, 0.15, 0.05])
    # round to whole rupees mostly (paise=00) with occasional odd paise
    val = rng.randint(lo, hi)
    if rng.chance(0.8):
        val = (val // 100) * 100
    return max(4900, val)


# --------------------------------------------------------------------------
# Settlement batch skeletons
# --------------------------------------------------------------------------
def build_batches(cfg: C.Config, rng: Rng) -> List[dict]:
    batches: List[dict] = []
    for day in range(2, cfg.n_days):
        for slot in range(cfg.settlements_per_day):
            settled_at = cfg.base_epoch + day * DAY + (9 + slot * 3) * 3600  # 09:00/12:00/15:00/18:00
            sid = ids.settlement_id(rng)
            utr = ids.settlement_utr(rng, settled_at)
            batches.append({
                "settlement_id": sid,
                "settlement_utr": utr,
                "settled_at": settled_at,
                "day": day,
                "rows": [],  # entity keys appended as rows are assigned
            })
    return batches


def _batches_on_or_after(batches: List[dict], day: int) -> List[dict]:
    return [b for b in batches if b["day"] >= day]


# --------------------------------------------------------------------------
# Main build
# --------------------------------------------------------------------------
def build(cfg: C.Config) -> dict:
    rng_amt = Rng(cfg.seed, "amount")
    rng_meth = Rng(cfg.seed, "method")
    rng_card = Rng(cfg.seed, "card")
    rng_id = Rng(cfg.seed, "ids")
    rng_time = Rng(cfg.seed, "time")
    rng_flag = Rng(cfg.seed, "flags")
    rng_fee = Rng(cfg.seed, "fee")
    rng_gst = Rng(cfg.seed, "gst")
    rng_desc = Rng(cfg.seed, "desc")
    rng_assign = Rng(cfg.seed, "assign")
    rng_carry = Rng(cfg.seed, "carry")

    batches = build_batches(cfg, rng_id)
    by_day: Dict[int, List[dict]] = {}
    for b in batches:
        by_day.setdefault(b["day"], []).append(b)

    # ---- Reserve carry-forward batches (SERIOUS-3) ----
    # A few settlement batches are deliberately starved of payments and later
    # seeded with refund/chargeback DEBITS so their net is <= 0. In bank.py these
    # roll forward into the next positive settlement (labeled carry_forward).
    # We reserve at most one batch per day (settlements_per_day=4) so every day
    # keeps assignable batches, and never on the first/last settlement day so a
    # later positive batch always exists to absorb the carry.
    n_carry = max(3, int(round(cfg.noise.carry_forward_rate * len(batches))))
    safe_days = [d for d in sorted(by_day) if 3 <= d <= cfg.n_days - 3
                 and len(by_day[d]) >= 2]
    carry_days = rng_carry.sample(safe_days, min(n_carry, len(safe_days)))
    carry_batches: List[dict] = []
    reserved = set()
    for d in carry_days:
        b = rng_carry.choice(by_day[d])
        carry_batches.append(b)
        reserved.add(b["settlement_id"])
    by_day_assignable: Dict[int, List[dict]] = {
        d: [b for b in bs if b["settlement_id"] not in reserved]
        for d, bs in by_day.items()
    }

    recon_rows: List[dict] = []
    orders: List[dict] = []
    fee_variance_ids: List[str] = []
    on_hold_ids: List[str] = []
    dispute_ids: List[str] = []

    payments: List[dict] = []  # keep parent refs for refunds/transfers/disputes
    cross_cycle_refund_ids: List[str] = []

    # ---- Payments + their orders ----
    for _ in range(cfg.n_payments):
        method = rng_meth.weighted_choice(list(C.METHOD_WEIGHTS), list(C.METHOD_WEIGHTS.values()))
        network, ctype, issuer = _card_fields(rng_card, method)
        amount = _amount(rng_amt)
        deviate = rng_fee.chance(cfg.noise.fee_variance_rate)
        direction_up = rng_fee.chance(0.5)  # RNG-drawn, not amount-parity (MINOR fix)
        fee = compute_fee(amount, method, network, ctype, deviate, direction_up)

        on_hold = rng_flag.chance(cfg.noise.on_hold_rate)
        created_day = rng_time.randint(0, cfg.n_days - 3)
        created_at = cfg.base_epoch + created_day * DAY + rng_time.randint(0, DAY - 1)

        pid = ids.payment_id(rng_id)
        oid = ids.order_id(rng_id)

        if on_hold:
            batch = None
            settled_at = None
            settlement_id = None
            settlement_utr = None
            settled = False
        else:
            pool = by_day_assignable.get(created_day + 2) or by_day[created_day + 2]
            batch = rng_assign.choice(pool)
            settled_at = batch["settled_at"]
            settlement_id = batch["settlement_id"]
            settlement_utr = batch["settlement_utr"]
            settled = True

        credit = amount - fee["fee"]
        row = {
            "entity_id": pid,
            "type": "payment",
            "debit": 0,
            "credit": credit,
            "amount": amount,
            "currency": CURRENCY,
            "fee": fee["fee"],
            "tax": fee["tax"],
            "on_hold": on_hold,
            "settled": settled,
            "created_at": created_at,
            "settled_at": settled_at,
            "settlement_id": settlement_id,
            "posted_at": None,
            "credit_type": "default",
            "description": rng_desc.choice(PAYMENT_DESCRIPTIONS),
            "notes": rng_desc.choice(["{}", None, "gift wrap", "priority ship"]),
            "payment_id": None,  # V3: NULL on payment rows
            "settlement_utr": settlement_utr,
            "order_id": oid,
            "order_receipt": None,
            "method": method,
            "card_network": network,
            "card_issuer": issuer,
            "card_type": ctype,
            "dispute_id": None,
        }
        recon_rows.append(row)
        if deviate and method != "upi":
            fee_variance_ids.append(pid)
        if on_hold:
            on_hold_ids.append(pid)
        if batch is not None:
            batch["rows"].append(["payment", pid])

        # matching order-ledger entry (clean; ledger corruption applied later)
        gst_rate = rng_gst.choice(C.GST_SLABS)
        base_excl = amount / (1.0 + gst_rate)
        gst_amount = amount - int(round(base_excl))
        order = {
            "order_id": oid,
            "amount": amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "status": "paid",
            "created_at": created_at,
            "receipt": f"rcpt_{rng_id.token(8)}",
            "payment_method": method,
        }
        orders.append(order)
        payments.append({
            "pid": pid, "oid": oid, "amount": amount, "method": method,
            "network": network, "ctype": ctype, "issuer": issuer,
            "created_at": created_at, "batch": batch,
            "created_day": created_day, "order": order,
        })

    order_by_id = {o["order_id"]: o for o in orders}

    # ---- Refunds (some cross-cycle: settle in a LATER batch than the payment) ----
    n_refunds = int(round(cfg.n_payments * cfg.noise.refund_rate))
    refund_parents = rng_flag.sample([p for p in payments if p["batch"] is not None],
                                     min(n_refunds, len([p for p in payments if p["batch"]])))
    for p in refund_parents:
        partial = rng_flag.chance(cfg.noise.partial_refund_rate)
        ramount = p["amount"] if not partial else max(4900, int(p["amount"] * rng_amt.choice([0.25, 0.5, 0.75])))
        parent_day = p["batch"]["day"]
        is_cross_cycle = False
        if rng_flag.chance(cfg.noise.cross_cycle_refund_rate):
            later = _batches_on_or_after(batches, parent_day + 1)
            if later:
                batch = rng_assign.choice(later)
                is_cross_cycle = True
            else:
                batch = p["batch"]
        else:
            batch = p["batch"]
        rid = ids.refund_id(rng_id)
        if is_cross_cycle:
            cross_cycle_refund_ids.append(rid)
        created_at = p["created_at"] + rng_time.randint(3600, 5 * DAY)
        row = {
            "entity_id": rid, "type": "refund", "debit": ramount, "credit": 0,
            "amount": ramount, "currency": CURRENCY, "fee": 0, "tax": 0,
            "on_hold": False, "settled": True, "created_at": created_at,
            "settled_at": batch["settled_at"], "settlement_id": batch["settlement_id"],
            "posted_at": None, "credit_type": "default", "description": None,
            "notes": rng_desc.choice(["{}", None]),
            "payment_id": p["pid"],  # populated on refund rows (verified)
            "settlement_utr": batch["settlement_utr"],
            "order_id": p["oid"], "order_receipt": None,
            "method": p["method"], "card_network": p["network"],
            "card_issuer": p["issuer"], "card_type": p["ctype"], "dispute_id": None,
        }
        recon_rows.append(row)
        batch["rows"].append(["refund", rid])
        order_by_id[p["oid"]]["status"] = "partially_refunded" if partial else "refunded"

    # ---- Disputes / chargebacks (V8): debit row with dispute_id, later batch ----
    n_disputes = int(round(cfg.n_payments * cfg.noise.dispute_rate))
    dispute_parents = rng_flag.sample([p for p in payments if p["batch"] is not None],
                                      min(n_disputes, len([p for p in payments if p["batch"]])))
    for p in dispute_parents:
        parent_day = p["batch"]["day"]
        later = _batches_on_or_after(batches, parent_day + 1)
        batch = rng_assign.choice(later) if later else p["batch"]
        rid = ids.refund_id(rng_id)
        did = "disp_" + rng_id.token(14)
        created_at = p["created_at"] + rng_time.randint(2 * DAY, 10 * DAY)
        row = {
            "entity_id": rid, "type": "refund", "debit": p["amount"], "credit": 0,
            "amount": p["amount"], "currency": CURRENCY, "fee": 0, "tax": 0,
            "on_hold": False, "settled": True, "created_at": created_at,
            "settled_at": batch["settled_at"], "settlement_id": batch["settlement_id"],
            "posted_at": None, "credit_type": "default",
            "description": "Chargeback debit", "notes": None,
            "payment_id": p["pid"], "settlement_utr": batch["settlement_utr"],
            "order_id": p["oid"], "order_receipt": None,
            "method": p["method"], "card_network": p["network"],
            "card_issuer": p["issuer"], "card_type": p["ctype"], "dispute_id": did,
        }
        recon_rows.append(row)
        batch["rows"].append(["refund", rid])
        dispute_ids.append(rid)
        order_by_id[p["oid"]]["status"] = "chargeback"

    # ---- Seed carry-forward batches (SERIOUS-3) ----
    # Each reserved carry batch has no payments; we attach 1-2 refund/chargeback
    # DEBIT rows (referencing payments settled in OTHER batches) so its net is
    # strictly negative. bank.py's roll-forward then carries these rows into the
    # next positive settlement, producing labeled `carry_forward` bank lines.
    carry_seed_refunds = 0
    settled_payments = [p for p in payments if p["batch"] is not None]
    for cb in carry_batches:
        n_seed = rng_carry.randint(1, 2)
        for _ in range(n_seed):
            p = rng_carry.choice(settled_payments)
            rid = ids.refund_id(rng_id)
            ramount = p["amount"]  # full refund -> guarantees net<=0 for the batch
            created_at = cb["settled_at"] - rng_time.randint(3600, 3 * DAY)
            row = {
                "entity_id": rid, "type": "refund", "debit": ramount, "credit": 0,
                "amount": ramount, "currency": CURRENCY, "fee": 0, "tax": 0,
                "on_hold": False, "settled": True, "created_at": created_at,
                "settled_at": cb["settled_at"], "settlement_id": cb["settlement_id"],
                "posted_at": None, "credit_type": "default",
                "description": "Refund (carried settlement)", "notes": None,
                "payment_id": p["pid"], "settlement_utr": cb["settlement_utr"],
                "order_id": p["oid"], "order_receipt": None,
                "method": p["method"], "card_network": p["network"],
                "card_issuer": p["issuer"], "card_type": p["ctype"], "dispute_id": None,
            }
            recon_rows.append(row)
            cb["rows"].append(["refund", rid])
            carry_seed_refunds += 1

    # ---- Route transfers (V2): debit = amount + fee, order_id NULL, method NULL ----
    # Exclude reserved carry batches so their net stays <= 0 (carry_forward).
    non_carry_batches = [b for b in batches if b["settlement_id"] not in reserved]
    n_transfers = int(round(cfg.n_payments * cfg.noise.transfer_rate))
    for _ in range(n_transfers):
        p = rng_assign.choice(payments)
        tamount = max(4900, int(p["amount"] * rng_amt.choice([0.2, 0.3, 0.5])))
        base_fee = int(round(tamount * cfg.noise.transfer_base_fee_rate))
        tax = int(round(base_fee * C.GST_ON_FEE_RATE))
        fee = base_fee + tax
        batch = rng_assign.choice(non_carry_batches)
        tid = ids.transfer_id(rng_id)
        created_at = p["created_at"] + rng_time.randint(0, 3 * DAY)
        row = {
            "entity_id": tid, "type": "transfer", "debit": tamount + fee, "credit": 0,
            "amount": tamount, "currency": CURRENCY, "fee": fee, "tax": tax,
            "on_hold": False, "settled": True, "created_at": created_at,
            "settled_at": batch["settled_at"], "settlement_id": batch["settlement_id"],
            "posted_at": None, "credit_type": "default", "description": None,
            "notes": None, "payment_id": p["pid"],  # transfer resolves via parent payment
            "settlement_utr": batch["settlement_utr"],
            "order_id": None, "order_receipt": None,  # order_id NULL on transfers (verified)
            "method": None, "card_network": None, "card_issuer": None,
            "card_type": None, "dispute_id": None,
        }
        recon_rows.append(row)
        batch["rows"].append(["transfer", tid])

    # ---- Adjustments (V1): no join key at all; credit_type OMITTED (V10) ----
    # Skip reserved carry batches: a positive adjustment credit could flip their
    # net back above zero and defeat the carry_forward construction.
    for batch in non_carry_batches:
        n_adj = 1 if rng_flag.chance(cfg.noise.adjustment_per_batch) else 0
        if n_adj and rng_flag.chance(0.15):
            n_adj = 2
        for _ in range(n_adj):
            aid = ids.adjustment_id(rng_id)
            is_credit = rng_flag.chance(0.5)
            amt = rng_amt.randint(1000, 250000)
            row = {
                "entity_id": aid, "type": "adjustment",
                "debit": 0 if is_credit else amt, "credit": amt if is_credit else 0,
                "amount": amt, "currency": CURRENCY, "fee": 0, "tax": 0,
                "on_hold": False, "settled": True, "created_at": batch["settled_at"] - DAY,
                "settled_at": batch["settled_at"], "settlement_id": batch["settlement_id"],
                "posted_at": None,
                # credit_type intentionally OMITTED (V10: vendor sources disagree)
                "description": rng_desc.choice(["test reason", "reserve adjustment",
                                                "chargeback reversal", "fee correction"]),
                "notes": None,
                "payment_id": None, "settlement_utr": None,  # NULL (V1)
                "order_id": None, "order_receipt": None,
                "method": None, "card_network": None, "card_issuer": None,
                "card_type": None, "dispute_id": None,
            }
            recon_rows.append(row)
            batch["rows"].append(["adjustment", aid])

    # index rows by (type, entity_id) for net computation
    row_index = {(r["type"], r["entity_id"]): r for r in recon_rows}
    for b in batches:
        net = 0
        for (t, eid) in b["rows"]:
            r = row_index[(t, eid)]
            net += r["credit"] - r["debit"]
        b["net"] = net

    return {
        "recon_rows": recon_rows,
        "orders": orders,
        "batches": batches,
        "row_index": row_index,
        "stats": {
            "payments": cfg.n_payments,
            "refunds": len(refund_parents),
            "disputes": len(dispute_parents),
            "transfers": n_transfers,
            "on_hold_rows": len(on_hold_ids),
            "fee_variance_rows": len(fee_variance_ids),
            "carry_batches_reserved": len(carry_batches),
            "carry_seed_refunds": carry_seed_refunds,
        },
        "fee_variance_ids": fee_variance_ids,
        "on_hold_ids": on_hold_ids,
        "dispute_ids": dispute_ids,
        "cross_cycle_refund_ids": cross_cycle_refund_ids,
    }

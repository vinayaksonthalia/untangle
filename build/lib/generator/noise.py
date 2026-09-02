"""
Merchant-ledger corruption (taxonomy M1/M2).

Kept as a separate, documented module so the corruption is auditable and its
rates are config, not magic numbers. This simulates the merchant's OWN export
from Shopify / Tally / WooCommerce being messy — the Razorpay recon report
itself stays clean (that asymmetry is the realistic part: the vendor's report
is tidy, the merchant's spreadsheet is not).

We record every corruption we make into `corruption_log` so ground truth /
manifest can report exact per-case counts and a reviewer can verify.
"""

from __future__ import annotations

from . import config as C
from .rng import Rng


def _mangle_order_id(oid: str, rng: Rng) -> str:
    mode = rng.choice(["truncate", "lower", "space", "prefix_drop", "typo"])
    if mode == "truncate":
        return oid[: max(6, len(oid) - rng.randint(2, 5))]
    if mode == "lower":
        return oid.lower()
    if mode == "space":
        return "  " + oid + " "
    if mode == "prefix_drop":
        return oid.replace("order_", "", 1)  # export stripped the prefix
    # typo: swap two adjacent chars in the body
    body = oid[len("order_"):]
    if len(body) > 3:
        i = rng.randint(0, len(body) - 2)
        body = body[:i] + body[i + 1] + body[i] + body[i + 2:]
    return "order_" + body


def corrupt_ledger(cfg: C.Config, orders: list[dict]) -> tuple[list[dict], dict[str, int]]:
    rng = Rng(cfg.seed, "ledger_noise")
    nr = cfg.noise
    counts = {"order_id_missing": 0, "order_id_mangled": 0, "order_id_duplicate": 0}

    out: list[dict] = []
    for o in orders:
        row = dict(o)
        r = rng.rand()
        # partition the corruption draws so rates don't overlap-inflate
        if r < nr.order_id_missing_rate:
            row["order_id"] = ""  # blank export cell (M1)
            counts["order_id_missing"] += 1
        elif r < nr.order_id_missing_rate + nr.order_id_mangled_rate:
            row["order_id"] = _mangle_order_id(o["order_id"], rng)
            counts["order_id_mangled"] += 1
        out.append(row)
        # duplicates are additive (a second physical row) — M2
        if rng.chance(nr.order_id_duplicate_rate):
            dup = dict(o)
            out.append(dup)
            counts["order_id_duplicate"] += 1

    rng.shuffle(out)  # exports are rarely in perfect order
    return out, counts

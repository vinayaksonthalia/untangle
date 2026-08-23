"""
Razorpay-style identifier construction.

Prefixes verified against fixtures/recon_sdk_node_2026-08-21.md:
  payment    -> pay_*     (the pay_ id lives in entity_id; payment_id is NULL — V3)
  refund     -> rfnd_*
  transfer   -> trf_*
  adjustment -> adj_*
  order      -> order_*
  settlement -> setl_*
Fixture id bodies are 14 base62 chars (e.g. pay_DEXrnipqTmWVGE); we match that.

UTR: fixture settlement_utr is "1568176960vxp0rj" — a 10-digit epoch-like prefix
followed by 6 lowercase base36 chars. We reproduce that shape so mangling in the
bank narration (B1) is realistic.
"""

from __future__ import annotations

from .rng import Rng


def _body(rng: Rng, n: int = 14) -> str:
    return rng.token(n)


def payment_id(rng: Rng) -> str:
    return "pay_" + _body(rng)


def refund_id(rng: Rng) -> str:
    return "rfnd_" + _body(rng)


def transfer_id(rng: Rng) -> str:
    return "trf_" + _body(rng)


def adjustment_id(rng: Rng) -> str:
    return "adj_" + _body(rng)


def order_id(rng: Rng) -> str:
    return "order_" + _body(rng)


def settlement_id(rng: Rng) -> str:
    return "setl_" + _body(rng)


def settlement_utr(rng: Rng, settled_at_epoch: int) -> str:
    """10-digit epoch-ish prefix + 6 base36 chars, matching fixture shape."""
    suffix_alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    suffix = "".join(rng.choice(suffix_alphabet) for _ in range(6))
    return f"{settled_at_epoch}{suffix}"

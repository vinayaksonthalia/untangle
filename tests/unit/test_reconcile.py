"""Reconciliation uses the SAME anchored UTR extractor as attribution (Qodo PR#9 #1).

Attribution rejects a UTR-shaped window sliced out of a longer numeric run; reconciliation
must apply the identical boundary rule, or a credit could be reconciled to the wrong
settlement via an embedded substring that attribution deliberately ignored.
"""

from __future__ import annotations

from datetime import date, datetime

from engine.models import BankCreditLine, ReconRow
from engine.reconcile import SettlementIndex


def _row(sid, utr, net, d="2026-06-10"):
    return ReconRow("pay_x", "payment", net, 0, 0, 0, net, sid, utr,
                    datetime.fromisoformat(f"{d}T00:00:00"), datetime(2026, 6, 9),
                    False, None, None, "upi", None)


def _line(narr, amount=100000, vd="2026-06-10"):
    return BankCreditLine("k", date.fromisoformat(vd), amount, narr, None, True)


def test_utr_sid_ignores_utr_embedded_in_longer_numeric_run():
    # 'setl_a' UTR is 1780498800xp8vma; embed it inside a 20-digit run so it is NOT a real token.
    idx = SettlementIndex([_row("setl_a", "1780498800xp8vma", 100000)])
    # A 24-char digit-ish blob that contains the UTR digits mid-run — anchored extractor must skip it.
    line = _line("NEFT REF 001780498800XP8VMA99 CR", amount=55555)
    assert idx.utr_sid(line) is None, "an embedded UTR substring must not resolve a settlement"


def test_utr_sid_matches_a_properly_delimited_utr():
    idx = SettlementIndex([_row("setl_a", "1780498800xp8vma", 100000)])
    line = _line("NEFT 1780498800xp8vma SETTLEMENT", amount=100000)
    assert idx.utr_sid(line) == "setl_a"

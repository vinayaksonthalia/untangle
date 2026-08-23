"""Reconcile the Razorpay-attributed slice against the recon report (spec FR-007, US2).

For each bank credit attributed ``razorpay_settlement``, resolve the exact set of recon
rows it covers and check the paise balance. Coverage is derived deterministically from the
recon report only — never from ground truth, never from the generator.

Safety (hardened after audit S1):
- A settlement is claimed by at most one bank credit (no double-cover).
- **UTR-first ordering**: credits with a decisive UTR tie are resolved in a first pass, so an
  amount-only credit can never steal a settlement that a UTR-tied credit will prove it owns.
- Every candidate path is **date-windowed** (incl. the single-net amount path) so a stale or
  coincidental amount match cannot balance a settlement from a distant date.
- A credit whose covering set cannot be found, or whose residual exceeds the drift tolerance,
  is left UNRESOLVED (→ US3 exception) rather than force-matched.
"""

from __future__ import annotations

import re
from itertools import combinations

from engine.models import BankCreditLine, Rail, RailAttribution, ReconciliationResult, ReconRow

_DRIFT_TOLERANCE_PAISE = 100      # ≤ ₹1 residual counts as balanced (labelled rounding drift)
_SETSUM_MAX_TERMS = 3
_SETSUM_MAX_CANDIDATES = 40
_DATE_WINDOW_DAYS = 5
_UTR = re.compile(r"[0-9]{10}[a-z0-9]{6}", re.I)


class SettlementIndex:
    """Settlement-grouped view of the recon report for coverage resolution."""

    def __init__(self, rows: list[ReconRow]) -> None:
        self.rows_by_sid: dict[str, list[ReconRow]] = {}
        self.utr_to_sid: dict[str, str] = {}
        self.net_by_sid: dict[str, int] = {}
        self.date_by_sid: dict[str, object] = {}
        for r in rows:
            sid = r.settlement_id
            if not sid:
                continue
            self.rows_by_sid.setdefault(sid, []).append(r)
            self.net_by_sid[sid] = self.net_by_sid.get(sid, 0) + r.net_paise
            if r.settlement_utr:
                self.utr_to_sid.setdefault(r.settlement_utr.lower(), sid)
            if r.settled_at is not None:
                self.date_by_sid[sid] = r.settled_at.date()
        self.net_to_sids: dict[int, list[str]] = {}
        for sid, n in self.net_by_sid.items():
            self.net_to_sids.setdefault(n, []).append(sid)

    def _within_window(self, sid: str, line: BankCreditLine) -> bool:
        d = self.date_by_sid.get(sid)
        return d is not None and abs((line.value_date - d).days) <= _DATE_WINDOW_DAYS

    def utr_sid(self, line: BankCreditLine) -> str | None:
        """A settlement whose settlement_utr appears verbatim in the credit — decisive."""
        for tok in _UTR.findall(line.raw_text()):
            sid = self.utr_to_sid.get(tok.lower())
            if sid is not None:
                return sid
        return None

    def amount_or_setsum_sids(self, line: BankCreditLine) -> list[str]:
        """A single settlement net (date-windowed) or a bounded, windowed set-sum, or []."""
        # single settlement whose net equals the credit amount, within the date window.
        sids = self.net_to_sids.get(line.amount_paise)
        if sids and len(sids) == 1 and self._within_window(sids[0], line):
            return [sids[0]]
        # bounded set-sum within the value-date window (merge / carry-forward).
        cands = [
            (sid, n)
            for sid, n in self.net_by_sid.items()
            if 0 < n < line.amount_paise and self._within_window(sid, line)
        ]
        if cands and len(cands) <= _SETSUM_MAX_CANDIDATES:
            for k in range(2, _SETSUM_MAX_TERMS + 1):
                for combo in combinations(cands, k):
                    if sum(n for _, n in combo) == line.amount_paise:
                        return [sid for sid, _ in combo]
        return []


def _make_result(
    line: BankCreditLine, sids: list[str], sindex: SettlementIndex
) -> ReconciliationResult | None:
    """Build a balanced ReconciliationResult, or None if the residual is out of tolerance."""
    covered = [r for s in sids for r in sindex.rows_by_sid.get(s, [])]
    covered_net = sum(r.net_paise for r in covered)
    residual = line.amount_paise - covered_net
    if abs(residual) > _DRIFT_TOLERANCE_PAISE:
        return None
    return ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[(r.type, r.entity_id) for r in covered],
        covered_net_paise=covered_net,
        credit_amount_paise=line.amount_paise,
        residual_paise=residual,
        balanced=True,
    )


def reconcile(
    lines_by_key: dict[str, BankCreditLine],
    attributions: list[RailAttribution],
    recon_rows: list[ReconRow],
) -> tuple[list[ReconciliationResult], list[str], SettlementIndex]:
    """Return (balanced reconciliations, unresolved razorpay line_keys, index).

    Two ordered passes (UTR-decisive first), deterministic, each settlement used once.
    """
    sindex = SettlementIndex(recon_rows)
    rzp = [a for a in attributions
           if a.rail == Rail.RAZORPAY_SETTLEMENT.value and a.line_key in lines_by_key]

    results: list[ReconciliationResult] = []
    used_sids: set[str] = set()
    resolved: set[str] = set()

    # Pass 1 — UTR-decisive claims. These own their settlement outright.
    for a in rzp:
        line = lines_by_key[a.line_key]
        sid = sindex.utr_sid(line)
        if sid is None or sid in used_sids:
            continue
        res = _make_result(line, [sid], sindex)
        if res is not None:
            results.append(res)
            used_sids.add(sid)
            resolved.add(a.line_key)

    # Pass 2 — amount / set-sum for what's left, against the remaining settlements.
    for a in rzp:
        if a.line_key in resolved:
            continue
        line = lines_by_key[a.line_key]
        sids = [s for s in sindex.amount_or_setsum_sids(line) if s not in used_sids]
        if not sids:
            continue
        res = _make_result(line, sids, sindex)
        if res is not None:
            results.append(res)
            used_sids.update(sids)
            resolved.add(a.line_key)

    unresolved = [a.line_key for a in rzp if a.line_key not in resolved]
    # Keep output order stable by attribution order.
    order = {a.line_key: i for i, a in enumerate(rzp)}
    results.sort(key=lambda r: order.get(r.line_key, 0))
    return results, unresolved, sindex

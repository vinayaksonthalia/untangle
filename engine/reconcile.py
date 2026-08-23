"""Reconcile the Razorpay-attributed slice against the recon report (spec FR-007, US2).

For each bank credit attributed ``razorpay_settlement``, resolve the exact set of recon
rows it covers and check the paise balance. Coverage is derived deterministically from the
recon report only — never from ground truth, never from the generator. A settlement is
claimed by at most one bank credit (no double-cover). A credit whose covering set cannot be
found, or whose residual exceeds the drift tolerance, is left UNRESOLVED (it becomes an
exception in US3) rather than force-matched.
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

    def sids_for_credit(self, line: BankCreditLine) -> list[str]:
        """Deterministically resolve which settlement(s) a credit covers, or []."""
        # 1) exact UTR tie — decisive.
        for tok in _UTR.findall(line.raw_text()):
            sid = self.utr_to_sid.get(tok.lower())
            if sid:
                return [sid]
        # 2) a single settlement whose net equals the credit amount.
        sids = self.net_to_sids.get(line.amount_paise)
        if sids and len(sids) == 1:
            return [sids[0]]
        # 3) bounded set-sum within the value-date window (merge / carry-forward).
        cands = [
            (sid, n)
            for sid, n in self.net_by_sid.items()
            if 0 < n < line.amount_paise
            and (d := self.date_by_sid.get(sid)) is not None
            and abs((line.value_date - d).days) <= _DATE_WINDOW_DAYS
        ]
        if cands and len(cands) <= _SETSUM_MAX_CANDIDATES:
            for k in range(2, _SETSUM_MAX_TERMS + 1):
                for combo in combinations(cands, k):
                    if sum(n for _, n in combo) == line.amount_paise:
                        return [sid for sid, _ in combo]
        return []


def reconcile(
    lines_by_key: dict[str, BankCreditLine],
    attributions: list[RailAttribution],
    recon_rows: list[ReconRow],
) -> tuple[list[ReconciliationResult], list[str], SettlementIndex]:
    """Return (balanced reconciliations, unresolved razorpay line_keys, index).

    Order-stable and deterministic. A settlement is used at most once.
    """
    sindex = SettlementIndex(recon_rows)
    results: list[ReconciliationResult] = []
    unresolved: list[str] = []
    used_sids: set[str] = set()

    for a in attributions:
        if a.rail != Rail.RAZORPAY_SETTLEMENT.value:
            continue
        line = lines_by_key.get(a.line_key)
        if line is None:
            continue
        sids = [s for s in sindex.sids_for_credit(line) if s not in used_sids]
        if not sids:
            unresolved.append(a.line_key)
            continue
        covered = [r for s in sids for r in sindex.rows_by_sid.get(s, [])]
        covered_net = sum(r.net_paise for r in covered)
        residual = line.amount_paise - covered_net
        if abs(residual) > _DRIFT_TOLERANCE_PAISE:
            unresolved.append(a.line_key)
            continue
        used_sids.update(sids)
        results.append(
            ReconciliationResult(
                line_key=a.line_key,
                covered_entity_ids=[(r.type, r.entity_id) for r in covered],
                covered_net_paise=covered_net,
                credit_amount_paise=line.amount_paise,
                residual_paise=residual,
                balanced=True,
            )
        )
    return results, unresolved, sindex

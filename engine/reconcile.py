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

from collections import defaultdict

from engine.bounded_subsets import find_bounded_subsets, find_legacy_subsets
from engine.covered import canonical_row_ids
from engine.evidence import extract_utr_tokens
from engine.models import BankCreditLine, Rail, RailAttribution, ReconciliationResult, ReconRow

_DRIFT_TOLERANCE_PAISE = 100      # ≤ ₹1 residual counts as balanced (labelled rounding drift)
_SETSUM_MAX_TERMS = 5
_SETSUM_MAX_CANDIDATES = 200     # candidate pool size up to N=200 per Phase 2
_SETSUM_EXPANSION_MAX_CANDIDATES = 16
_SETSUM_MAX_COMBINATIONS = 100_000
_DATE_WINDOW_DAYS = 5


class SettlementIndex:
    """Settlement-grouped view of the recon report for coverage resolution."""

    def __init__(self, rows: list[ReconRow]) -> None:
        self.rows_by_sid: dict[str, list[ReconRow]] = {}
        self.utr_to_sid: dict[str, str] = {}
        self.net_by_sid: dict[str, int] = {}
        self.date_by_sid: dict[str, object] = {}
        # Content-derived canonical identity: independent of list position, so a covered id can never
        # silently rebind to a different physical row if recon_rows is later reordered/subset. The
        # untrusted external ReconRow.row_id is deliberately ignored (see engine.covered).
        self.row_ids: dict[int, str] = canonical_row_ids(rows)
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
        self.ambiguous_lines: set[str] = set()
        self.un_enumerable_lines: set[str] = set()
        self.duplicate_or_split_lines: set[str] = set()
        self.unbalanced_lines: dict[str, int] = {}
        self.uncredited_sids: set[str] = set()

    def _within_window(self, sid: str, line: BankCreditLine) -> bool:
        d = self.date_by_sid.get(sid)
        return d is not None and abs((line.value_date - d).days) <= _DATE_WINDOW_DAYS

    def utr_sid(self, line: BankCreditLine) -> str | None:
        """A settlement whose settlement_utr appears verbatim in the credit — decisive."""
        for tok in extract_utr_tokens(line.raw_text()):
            sid = self.utr_to_sid.get(tok.lower())
            if sid is not None:
                return sid
        return None

    def amount_or_setsum_sids(
        self, line: BankCreditLine, used_sids: set[str] | None = None
    ) -> list[str]:
        """A single settlement net or bounded windowed set-sum, or [].

        The established 2–3-term search remains exact for up to 200 candidates. The
        4–5-term expansion runs only for pools of up to 16 candidates and is exact
        within its explicit combination budget. If >1 distinct subset satisfies the
        amount, abstains (returns []) and records the line in ambiguous_lines
        (G2/FR-003).
        """
        used = used_sids or set()
        satisfying_subsets: list[list[str]] = []
        seen_subsets: set[frozenset[str]] = set()

        # 1. Single settlement whose net equals the credit amount, within the date window.
        single_sids = self.net_to_sids.get(line.amount_paise, [])
        for sid in single_sids:
            if sid not in used and self._within_window(sid, line):
                subset = frozenset([sid])
                if subset not in seen_subsets:
                    seen_subsets.add(subset)
                    satisfying_subsets.append([sid])

        # 2. Bounded set-sum within the value-date window (merge / carry-forward).
        cands = [
            (sid, n)
            for sid, n in self.net_by_sid.items()
            if sid not in used and 0 < n < line.amount_paise and self._within_window(sid, line)
        ]
        if cands and len(cands) <= _SETSUM_MAX_CANDIDATES:
            if len(cands) <= _SETSUM_EXPANSION_MAX_CANDIDATES:
                search = find_bounded_subsets(
                    cands,
                    line.amount_paise,
                    max_terms=_SETSUM_MAX_TERMS,
                    max_items=_SETSUM_EXPANSION_MAX_CANDIDATES,
                    max_combinations=_SETSUM_MAX_COMBINATIONS,
                    sort_items=False,
                )
            else:
                search = find_legacy_subsets(cands, line.amount_paise)
            if search.exhausted:
                self.un_enumerable_lines.add(line.key)
                return []
            for subset in search.subsets:
                frozen = frozenset(subset)
                if frozen not in seen_subsets:
                    seen_subsets.add(frozen)
                    satisfying_subsets.append(list(subset))

        if len(satisfying_subsets) > 1:
            self.ambiguous_lines.add(line.key)
            return []

        if len(satisfying_subsets) == 1:
            return satisfying_subsets[0]

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
        covered_row_ids=[sindex.row_ids[id(r)] for r in covered],
    )


def reconcile(
    lines_by_key: dict[str, BankCreditLine],
    attributions: list[RailAttribution],
    recon_rows: list[ReconRow],
) -> tuple[list[ReconciliationResult], list[str], SettlementIndex]:
    """Return (balanced reconciliations, unresolved razorpay line_keys, index).

    Reconciles ONLY the proven-Razorpay slice (never an abstained credit),
    keyed on settlement_id. Two ordered passes (UTR-decisive first), deterministic,
    each settlement used at most once. Surfaces residuals and partial/duplicate cases (FR-016).
    """
    sindex = SettlementIndex(recon_rows)
    # Reconcile ONLY the proven-Razorpay slice (never an abstained credit)
    rzp = [
        a for a in attributions
        if a.rail == Rail.RAZORPAY_SETTLEMENT.value and not a.abstained and a.line_key in lines_by_key
    ]

    results: list[ReconciliationResult] = []
    used_sids: set[str] = set()
    resolved: set[str] = set()

    # Pass 1 — UTR-decisive claims.
    # Group claims to detect settlements claimed by >1 bank credit (FR-016 duplicate / split payout).
    utr_claims: dict[str, list[str]] = defaultdict(list)
    for a in rzp:
        line = lines_by_key[a.line_key]
        sid = sindex.utr_sid(line)
        if sid is not None:
            utr_claims[sid].append(a.line_key)

    for sid, claim_keys in utr_claims.items():
        if len(claim_keys) > 1:
            # Settlement maps to >1 bank credit (FR-016).
            # Record all as duplicate/split exceptions; NEVER net them together to force balance.
            sindex.duplicate_or_split_lines.update(claim_keys)
            continue
        line_key = claim_keys[0]
        line = lines_by_key[line_key]
        res = _make_result(line, [sid], sindex)
        if res is not None:
            results.append(res)
            used_sids.add(sid)
            resolved.add(line_key)

    # Pass 2 — amount / set-sum for what's left, against the remaining settlements.
    for a in rzp:
        if a.line_key in resolved or a.line_key in sindex.duplicate_or_split_lines:
            continue
        line = lines_by_key[a.line_key]
        sids = sindex.amount_or_setsum_sids(line, used_sids=used_sids)
        if not sids:
            continue
        res = _make_result(line, sids, sindex)
        if res is not None:
            results.append(res)
            used_sids.update(sids)
            resolved.add(a.line_key)

    # After Pass 1 and Pass 2: classify remaining unresolved lines
    unresolved = [a.line_key for a in rzp if a.line_key not in resolved]
    for u in unresolved:
        line = lines_by_key[u]
        sid = sindex.utr_sid(line)
        if sid and sid in sindex.rows_by_sid:
            covered_net = sum(r.net_paise for r in sindex.rows_by_sid[sid])
            res = line.amount_paise - covered_net
            if line.amount_paise < covered_net:
                sindex.duplicate_or_split_lines.add(u)
            else:
                sindex.unbalanced_lines[u] = res

    # Record uncredited settlements (settlement_id in report mapped to zero bank credits)
    sindex.uncredited_sids = set(sindex.rows_by_sid.keys()) - used_sids

    unresolved = [a.line_key for a in rzp if a.line_key not in resolved]
    # Keep output order stable by attribution order.
    order = {a.line_key: i for i, a in enumerate(rzp)}
    results.sort(key=lambda r: order.get(r.line_key, 0))
    return results, unresolved, sindex

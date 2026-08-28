"""Agentic Exception-Investigation Loop (Feature 006).

For Razorpay bank credits that exhibit a reconciliation failure (unbalanced_residual,
partial_or_duplicate_settlement, reconstructed_split_leg, razorpay_coverage_not_found),
diagnoses the root cause deterministically from the underlying settlement, recon, and fee data.

Guarantees:
  1. Deterministic Core: pure functions classify the root cause; no LLM in decision logic.
  2. Additive & Read-Only: does not alter any existing attribution, reconciliation, or metric.
  3. Abstain Over Guess: if no class closes the delta within tolerance, returns 'unexplained'.
  4. Balanced Corrective Entry: drafted double-entry voucher balances to 0.00 exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.evidence import ReconIndex
from engine.journal import (
    LEDGER_CLEARING,
    LEDGER_MDR,
    LEDGER_ROUNDING,
    JournalEntry,
    JournalLine,
    _inr,
)
from engine.models import (
    BankCreditLine,
    ExceptionRecord,
    RailAttribution,
    ReconciliationResult,
    ReconRow,
)

# Root-Cause Taxonomy (ordered priority per HANDOFF.md §3b)
ROOT_CAUSE_MDR_FEE_DRIFT = "mdr_fee_drift"
ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG = "cross_cycle_refund_lag"
ROOT_CAUSE_ON_HOLD_RELEASE = "on_hold_release"
ROOT_CAUSE_DISPUTE_DEDUCTION = "dispute_deduction"
ROOT_CAUSE_PARTIAL_CAPTURE = "partial_capture"
ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING = "bank_charge_or_rounding"
ROOT_CAUSE_ROLLING_RESERVE = "rolling_reserve"
ROOT_CAUSE_UNEXPLAINED = "unexplained"

ROOT_CAUSE_TAXONOMY: tuple[str, ...] = (
    ROOT_CAUSE_MDR_FEE_DRIFT,
    ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG,
    ROOT_CAUSE_ON_HOLD_RELEASE,
    ROOT_CAUSE_DISPUTE_DEDUCTION,
    ROOT_CAUSE_PARTIAL_CAPTURE,
    ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING,
    ROOT_CAUSE_ROLLING_RESERVE,
    ROOT_CAUSE_UNEXPLAINED,
)

# Standard D2C Ledger Accounts for Corrective Entries
LEDGER_DISPUTES = "Disputed Receivables A/c"
LEDGER_ON_HOLD = "On-Hold Settlement Reserve A/c"
LEDGER_ROLLING_RESERVE = "Rolling Reserve Asset A/c"
LEDGER_REFUND_SUSPENSE = "Cross-Cycle Refund Suspense A/c"
LEDGER_UNCAPTURED = "Uncaptured Order Variance A/c"

_TOLERANCE_PAISE = 100  # ±₹1 tolerance


@dataclass(frozen=True)
class Investigation:
    """An autonomous investigation into a reconciliation variance."""

    line_key: str
    variance_paise: int
    root_cause: str
    confidence: float
    reasoning_trace: list[str]
    corrective_entry: dict[str, Any] | None
    candidates_tried: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_key": self.line_key,
            "variance_paise": self.variance_paise,
            "variance_inr": _inr(abs(self.variance_paise)),
            "root_cause": self.root_cause,
            "confidence": round(self.confidence, 4),
            "reasoning_trace": list(self.reasoning_trace),
            "corrective_entry": self.corrective_entry,
            "candidates_tried": list(self.candidates_tried),
        }


def _format_inr(paise: int) -> str:
    """Format paise with sign and currency symbol."""
    sign = "-" if paise < 0 else "+" if paise > 0 else ""
    return f"{sign}₹{abs(paise) / 100:,.2f}"


def _make_corrective_entry(
    line: BankCreditLine,
    root_cause: str,
    variance_paise: int,
    ref: str,
    date_str: str,
    utr_str: str,
) -> dict[str, Any]:
    """Draft a balanced double-entry corrective journal voucher for the explained variance."""
    abs_var = abs(variance_paise)
    lines: list[JournalLine] = []

    if root_cause == ROOT_CAUSE_MDR_FEE_DRIFT:
        # Variance due to MDR fee deduction difference
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_MDR, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_MDR, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG:
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_REFUND_SUSPENSE, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_REFUND_SUSPENSE, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_ON_HOLD_RELEASE:
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_ON_HOLD, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_ON_HOLD, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_DISPUTE_DEDUCTION:
        lines.append(JournalLine(LEDGER_DISPUTES, debit_paise=abs_var))
        lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_PARTIAL_CAPTURE:
        lines.append(JournalLine(LEDGER_UNCAPTURED, debit_paise=abs_var))
        lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING:
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_ROUNDING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_ROUNDING, credit_paise=abs_var))

    elif root_cause == ROOT_CAUSE_ROLLING_RESERVE:
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_ROLLING_RESERVE, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_ROLLING_RESERVE, credit_paise=abs_var))

    else:
        # Generic balancing fallback
        if variance_paise < 0:
            lines.append(JournalLine(LEDGER_ROUNDING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_CLEARING, credit_paise=abs_var))
        else:
            lines.append(JournalLine(LEDGER_CLEARING, debit_paise=abs_var))
            lines.append(JournalLine(LEDGER_ROUNDING, credit_paise=abs_var))

    narration = (
        f"Proposed adjustment for {root_cause} | Bank credit {line.key} | "
        f"Variance {_format_inr(variance_paise)} | PROPOSAL ONLY - NOT POSTED"
    )

    entry = JournalEntry(
        ref=f"ADJ-{ref}",
        date=date_str,
        utr=utr_str,
        narration=narration,
        lines=tuple(lines),
    )
    assert entry.balanced, f"Corrective journal entry must balance: {entry}"
    return entry.to_dict()


def investigate(
    line: BankCreditLine,
    attribution: RailAttribution | None,
    reconciliation: ReconciliationResult | None,
    recon_rows: list[ReconRow],
    index: ReconIndex,
    exception: ExceptionRecord | dict | None = None,
) -> Investigation:
    """Classify the root cause of variance for a Razorpay credit deterministically."""
    reasoning_trace: list[str] = []
    candidates_tried: list[dict[str, Any]] = []

    # 1. Establish the baseline and compute variance
    line_amount = line.amount_paise
    expected_net = 0
    ref_id = line.key
    date_str = line.value_date.isoformat()
    utr_str = line.bank_ref or ""

    # Find associated settlement rows. Index as a MULTIMAP so duplicate (type, entity_id) rows are
    # not collapsed to the last one (the domain genuinely produces them) — consume one distinct row
    # per covered-key occurrence, mirroring the journal/feegst/proof fix.
    from collections import defaultdict

    associated_rows: list[ReconRow] = []
    rows_by_key: dict[tuple[str, str], list[ReconRow]] = defaultdict(list)
    for r in recon_rows:
        rows_by_key[(r.type, r.entity_id)].append(r)

    if reconciliation is not None and reconciliation.covered_entity_ids:
        expected_net = reconciliation.covered_net_paise
        _seen: dict[tuple[str, str], int] = defaultdict(int)
        for k in reconciliation.covered_entity_ids:
            bucket = rows_by_key.get(k, [])
            if _seen[k] < len(bucket):
                associated_rows.append(bucket[_seen[k]])
            _seen[k] += 1
        if associated_rows:
            sid = next((r.settlement_id for r in associated_rows if r.settlement_id), line.key)
            ref_id = str(sid)
            s_utr = next((r.settlement_utr for r in associated_rows if r.settlement_utr), "")
            if s_utr:
                utr_str = s_utr
            s_date = next((r.settled_at for r in associated_rows if r.settled_at), None)
            if s_date:
                date_str = s_date.date().isoformat()
    else:
        # No reconciliation object (unresolved credit): recover the candidate settlement from the
        # narration/ref using BOTH exact and corroborated-suffix UTR ties (the same ties attribution
        # uses), not just a verbatim full UTR. If more than one distinct settlement is implicated the
        # association is AMBIGUOUS — we do NOT pick one arbitrarily; we leave it unassociated so the
        # guard below abstains (association-ambiguous → abstain, never guess).
        candidate_sids: set[str] = set()
        for tok in (line.bank_ref, line.narration):
            if tok:
                for word in tok.replace("/", " ").replace("-", " ").split():
                    w = word.lower()
                    sid = None
                    if index.utr_exact(w):
                        sid = index.utr_to_sid.get(w)
                    else:
                        matched_utr = index.utr_suffix_match(w)
                        if matched_utr:
                            sid = index.utr_to_sid.get(matched_utr)
                    if sid:
                        candidate_sids.add(sid)
        if len(candidate_sids) == 1:
            sid = next(iter(candidate_sids))
            ref_id = sid
            expected_net = index.settlement_net.get(sid, 0)
            associated_rows = [r for r in recon_rows if r.settlement_id == sid]

    # Abstain when no settlement context could be associated. For an unresolved credit
    # (reconciliation is None and no settlement matched by UTR), we have no expected net to compare
    # against — computing a "variance" against 0 would be meaningless and any classifier match would
    # be a guess. Abstain explicitly rather than fabricate a variance from missing context.
    if not associated_rows:
        reasoning_trace.append(
            "Step 1: No settlement context could be associated with this unresolved credit "
            "(no covered settlement rows, and no settlement matched by UTR) — there is no expected "
            "net to compare against. Abstaining (root_cause='unexplained') rather than guessing."
        )
        return Investigation(
            line_key=line.key,
            variance_paise=0,
            root_cause=ROOT_CAUSE_UNEXPLAINED,
            confidence=0.0,
            reasoning_trace=reasoning_trace,
            corrective_entry=None,
            candidates_tried=[],
        )

    variance_paise = line_amount - expected_net

    reasoning_trace.append(
        f"Step 1: Computed variance: Bank credit ({_format_inr(line_amount)}) vs "
        f"Expected settlement net ({_format_inr(expected_net)}) -> Delta: {_format_inr(variance_paise)} "
        f"({variance_paise} paise)."
    )

    if abs(variance_paise) == 0:
        # Zero variance: fully balanced
        reasoning_trace.append("Step 2: Delta is 0 paise; credit balances exactly.")
        return Investigation(
            line_key=line.key,
            variance_paise=0,
            root_cause="balanced",
            confidence=1.0,
            reasoning_trace=reasoning_trace,
            corrective_entry=None,
            candidates_tried=[],
        )

    # -------------------------------------------------------------------------
    # Classifier 1: mdr_fee_drift
    # -------------------------------------------------------------------------
    matched_cause: str | None = None
    confidence = 0.0
    matched_delta = 0

    fee_sum = sum(r.fee_paise for r in associated_rows)
    tax_sum = sum(r.tax_paise for r in associated_rows)
    mdr_matches = False
    mdr_reason = ""

    # Case A: Tax inside vs outside fee convention (delta equals tax_sum)
    if tax_sum > 0 and abs(abs(variance_paise) - tax_sum) <= _TOLERANCE_PAISE:
        mdr_matches = True
        matched_delta = -tax_sum if variance_paise < 0 else tax_sum
        mdr_reason = f"Fee tax-inside/outside convention difference matches variance: {_format_inr(tax_sum)}"
    # Case B: Recomputed fee slab difference
    elif fee_sum > 0:
        # Test if standard 2% (+18% GST) fee on gross differs from fee_sum by variance
        gross = sum(r.amount_paise for r in associated_rows if r.type == "payment")
        if gross > 0:
            std_fee = round(gross * 0.02 * 1.18)
            fee_drift = fee_sum - std_fee
            # SIGNED match: a fee higher than standard (positive drift) leaves the merchant SHORT
            # (negative variance), so the effect is -fee_drift. Require it to close the variance in
            # the correct direction — an opposite-direction variance must NOT match.
            if abs(variance_paise - (-fee_drift)) <= _TOLERANCE_PAISE:
                mdr_matches = True
                matched_delta = -fee_drift
                mdr_reason = f"MDR fee-slab recompute drift ({_format_inr(fee_drift)}) accounts for variance"

    if mdr_matches:
        candidates_tried.append({
            "root_cause": ROOT_CAUSE_MDR_FEE_DRIFT,
            "matched": True,
            "delta_paise": matched_delta,
            "unexplained_residual_paise": abs(variance_paise - matched_delta),
            "reason": mdr_reason,
        })
        matched_cause = ROOT_CAUSE_MDR_FEE_DRIFT
        residual_err = abs(variance_paise - matched_delta)
        confidence = round(1.0 - (residual_err / 100.0) * 0.1, 4) if residual_err <= _TOLERANCE_PAISE else 0.95
        reasoning_trace.append(f"Step 2: Evaluated '{ROOT_CAUSE_MDR_FEE_DRIFT}' -> MATCH: {mdr_reason}.")
    else:
        candidates_tried.append({
            "root_cause": ROOT_CAUSE_MDR_FEE_DRIFT,
            "matched": False,
            "delta_paise": 0,
            "unexplained_residual_paise": abs(variance_paise),
            "reason": "MDR fee recalculation does not account for variance.",
        })
        reasoning_trace.append(f"Step 2: Evaluated '{ROOT_CAUSE_MDR_FEE_DRIFT}' -> NO MATCH.")

    # -------------------------------------------------------------------------
    # Classifier 2: cross_cycle_refund_lag
    # -------------------------------------------------------------------------
    if not matched_cause:
        # Scope refunds to THIS credit's own settlement(s). Scanning the whole dataset would
        # force-fit any refund whose amount coincidentally equals the variance — a guess, not
        # evidence (abstain-over-guess). And require the refund to actually cross a cycle boundary
        # (created in one cycle, settled in a later one): that lag is precisely what leaves this
        # credit short. No settlement scope or no cross-cycle date → no match (we abstain here).
        assoc_sids = {r.settlement_id for r in associated_rows if r.settlement_id}
        refund_candidates = [
            r for r in recon_rows
            if r.settlement_id in assoc_sids
            and (r.type == "refund" or (r.type == "adjustment" and "refund" in (r.description or "").lower()))
        ] if assoc_sids else []
        refund_match = None
        refund_amt = 0
        for r in refund_candidates:
            # Debit-only refund rows carry the amount in debit_paise, not amount_paise.
            ref_amt = r.amount_paise or r.debit_paise
            crosses_cycle = (
                r.created_at is not None and r.settled_at is not None
                and r.settled_at.date() > r.created_at.date()
            )
            # SIGNED match: a refund reduces the credit, so it explains a NEGATIVE variance of ~ref_amt
            # (variance ≈ -ref_amt). A positive variance must NOT be explained by a refund.
            if crosses_cycle and ref_amt > 0 and abs(variance_paise + ref_amt) <= _TOLERANCE_PAISE:
                refund_match = r
                refund_amt = ref_amt
                break

        if refund_match:
            matched_cause = ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG
            matched_delta = -refund_amt
            residual_err = abs(variance_paise - matched_delta)
            confidence = round(1.0 - (residual_err / 100.0) * 0.1, 4) if residual_err <= _TOLERANCE_PAISE else 0.90
            r_detail = f"Cross-cycle refund '{refund_match.entity_id}' of {_format_inr(refund_amt)} accounts for variance"
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG,
                "matched": True,
                "delta_paise": matched_delta,
                "unexplained_residual_paise": residual_err,
                "reason": r_detail,
            })
            reasoning_trace.append(f"Step 3: Evaluated '{ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG}' -> MATCH: {r_detail}.")
        else:
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG,
                "matched": False,
                "delta_paise": 0,
                "unexplained_residual_paise": abs(variance_paise),
                "reason": "No cross-cycle refund row matches the variance amount.",
            })
            reasoning_trace.append(f"Step 3: Evaluated '{ROOT_CAUSE_CROSS_CYCLE_REFUND_LAG}' -> NO MATCH.")

    # -------------------------------------------------------------------------
    # Classifier 3: on_hold_release
    # -------------------------------------------------------------------------
    if not matched_cause:
        on_hold_rows = [r for r in associated_rows if r.on_hold]
        on_hold_sum = sum(r.amount_paise for r in on_hold_rows) if on_hold_rows else 0

        # on_hold_release is BIDIRECTIONAL: an amount can be WITHHELD (credit short → negative
        # variance) OR RELEASED into this cycle (→ positive variance). Match the magnitude in either
        # direction and let matched_delta follow the actual variance direction (the voucher direction
        # follows matched_delta). Only pure deductions (dispute/refund/partial) are sign-restricted.
        if on_hold_sum > 0 and abs(abs(variance_paise) - on_hold_sum) <= _TOLERANCE_PAISE:
            matched_cause = ROOT_CAUSE_ON_HOLD_RELEASE
            matched_delta = -on_hold_sum if variance_paise < 0 else on_hold_sum
            residual_err = abs(variance_paise - matched_delta)
            confidence = round(1.0 - (residual_err / 100.0) * 0.1, 4) if residual_err <= _TOLERANCE_PAISE else 0.90
            h_detail = f"On-hold amount of {_format_inr(on_hold_sum)} matches variance exactly"
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_ON_HOLD_RELEASE,
                "matched": True,
                "delta_paise": matched_delta,
                "unexplained_residual_paise": residual_err,
                "reason": h_detail,
            })
            reasoning_trace.append(f"Step 4: Evaluated '{ROOT_CAUSE_ON_HOLD_RELEASE}' -> MATCH: {h_detail}.")
        else:
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_ON_HOLD_RELEASE,
                "matched": False,
                "delta_paise": 0,
                "unexplained_residual_paise": abs(variance_paise),
                "reason": "No matching on-hold transactions in settlement.",
            })
            reasoning_trace.append(f"Step 4: Evaluated '{ROOT_CAUSE_ON_HOLD_RELEASE}' -> NO MATCH.")

    # -------------------------------------------------------------------------
    # Classifier 4: dispute_deduction
    # -------------------------------------------------------------------------
    if not matched_cause:
        dispute_rows = [r for r in associated_rows if r.dispute_id is not None]
        dispute_sum = sum(r.amount_paise for r in dispute_rows) if dispute_rows else 0

        # SIGNED match: a dispute/chargeback is a DEDUCTION — it explains a negative variance of
        # ~dispute_sum only (variance ≈ -dispute_sum), never a positive overage.
        if dispute_sum > 0 and abs(variance_paise + dispute_sum) <= _TOLERANCE_PAISE:
            matched_cause = ROOT_CAUSE_DISPUTE_DEDUCTION
            matched_delta = -dispute_sum
            residual_err = abs(variance_paise - matched_delta)
            confidence = round(1.0 - (residual_err / 100.0) * 0.1, 4) if residual_err <= _TOLERANCE_PAISE else 0.95
            d_detail = f"Dispute deduction '{dispute_rows[0].dispute_id}' of {_format_inr(dispute_sum)} accounts for variance"
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_DISPUTE_DEDUCTION,
                "matched": True,
                "delta_paise": matched_delta,
                "unexplained_residual_paise": residual_err,
                "reason": d_detail,
            })
            reasoning_trace.append(f"Step 5: Evaluated '{ROOT_CAUSE_DISPUTE_DEDUCTION}' -> MATCH: {d_detail}.")
        else:
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_DISPUTE_DEDUCTION,
                "matched": False,
                "delta_paise": 0,
                "unexplained_residual_paise": abs(variance_paise),
                "reason": "No dispute deduction found matching variance.",
            })
            reasoning_trace.append(f"Step 5: Evaluated '{ROOT_CAUSE_DISPUTE_DEDUCTION}' -> NO MATCH.")

    # -------------------------------------------------------------------------
    # Classifier 5: partial_capture
    # -------------------------------------------------------------------------
    if not matched_cause:
        # Partial capture (captured < authorized) is NOT deterministically expressible on this
        # schema: ReconRow carries no authorized-vs-captured amounts. Detecting it from free text
        # (e.g. the word "partial" in a description) would be a guess and could post a full captured
        # payment as an uncaptured variance — so we SKIP this classifier rather than infer it. It
        # will be enabled only if/when the settlement schema carries explicit authorized/captured
        # fields. (Skip-not-guess, per the abstention contract.)
        _has_capture_fields = False  # no authorized/captured columns on ReconRow today
        if _has_capture_fields:  # pragma: no cover - reserved for a schema that carries capture data
            pass
        candidates_tried.append({
            "root_cause": ROOT_CAUSE_PARTIAL_CAPTURE,
            "matched": False,
            "delta_paise": 0,
            "unexplained_residual_paise": abs(variance_paise),
            "reason": "Skipped: the settlement schema carries no authorized/captured amounts, so "
                      "partial capture cannot be determined deterministically (never inferred from text).",
        })
        reasoning_trace.append(
            f"Step 6: Evaluated '{ROOT_CAUSE_PARTIAL_CAPTURE}' -> SKIPPED "
            f"(no deterministic authorized/captured evidence in the schema; not inferred from text)."
        )

    # -------------------------------------------------------------------------
    # Classifier 6: bank_charge_or_rounding
    # -------------------------------------------------------------------------
    if not matched_cause:
        if abs(variance_paise) <= _TOLERANCE_PAISE:
            matched_cause = ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING
            matched_delta = variance_paise
            confidence = round(1.0 - (abs(variance_paise) / 100.0) * 0.15, 4)
            b_detail = f"Residual drift {_format_inr(variance_paise)} is within ±₹1 rounding tolerance"
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING,
                "matched": True,
                "delta_paise": matched_delta,
                "unexplained_residual_paise": 0,
                "reason": b_detail,
            })
            reasoning_trace.append(f"Step 7: Evaluated '{ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING}' -> MATCH: {b_detail}.")
        else:
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING,
                "matched": False,
                "delta_paise": 0,
                "unexplained_residual_paise": abs(variance_paise),
                "reason": f"Variance {_format_inr(variance_paise)} exceeds ±₹1 rounding tolerance.",
            })
            reasoning_trace.append(f"Step 7: Evaluated '{ROOT_CAUSE_BANK_CHARGE_OR_ROUNDING}' -> NO MATCH.")

    # -------------------------------------------------------------------------
    # Classifier 7: rolling_reserve (GATED on real data in schema)
    # -------------------------------------------------------------------------
    if not matched_cause:
        # Refinement 1: Gated on real data — only check if settlement schema actually carries reserve rows
        reserve_rows = [
            r for r in associated_rows
            if r.type == "reserve" or (r.description and "reserve" in r.description.lower())
        ]
        reserve_sum = sum(r.amount_paise for r in reserve_rows) if reserve_rows else 0

        # rolling_reserve is BIDIRECTIONAL like on_hold: a reserve can be WITHHELD (credit short →
        # negative variance) OR RELEASED back into this cycle (→ positive variance). Match the
        # magnitude in either direction; matched_delta follows the actual variance direction and the
        # voucher direction follows matched_delta.
        if reserve_sum > 0 and abs(abs(variance_paise) - reserve_sum) <= _TOLERANCE_PAISE:
            matched_cause = ROOT_CAUSE_ROLLING_RESERVE
            matched_delta = -reserve_sum if variance_paise < 0 else reserve_sum
            residual_err = abs(variance_paise - matched_delta)
            confidence = round(1.0 - (residual_err / 100.0) * 0.1, 4) if residual_err <= _TOLERANCE_PAISE else 0.85
            rr_detail = f"Explicit rolling reserve row matches variance: {_format_inr(reserve_sum)}"
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_ROLLING_RESERVE,
                "matched": True,
                "delta_paise": matched_delta,
                "unexplained_residual_paise": residual_err,
                "reason": rr_detail,
            })
            reasoning_trace.append(f"Step 8: Evaluated '{ROOT_CAUSE_ROLLING_RESERVE}' -> MATCH: {rr_detail}.")
        else:
            candidates_tried.append({
                "root_cause": ROOT_CAUSE_ROLLING_RESERVE,
                "matched": False,
                "delta_paise": 0,
                "unexplained_residual_paise": abs(variance_paise),
                "reason": "No explicit rolling reserve records present in settlement data.",
            })
            reasoning_trace.append(f"Step 8: Evaluated '{ROOT_CAUSE_ROLLING_RESERVE}' -> NO MATCH (gated on real data).")

    # -------------------------------------------------------------------------
    # Classifier 8: unexplained (Abstain over guess)
    # -------------------------------------------------------------------------
    if not matched_cause:
        matched_cause = ROOT_CAUSE_UNEXPLAINED
        confidence = 0.0
        reasoning_trace.append(
            f"Step 9: All 7 candidate root-cause classes evaluated without a match -> "
            f"Abstaining with root_cause='{ROOT_CAUSE_UNEXPLAINED}' (no guesses made)."
        )
        return Investigation(
            line_key=line.key,
            variance_paise=variance_paise,
            root_cause=ROOT_CAUSE_UNEXPLAINED,
            confidence=0.0,
            reasoning_trace=reasoning_trace,
            corrective_entry=None,
            candidates_tried=candidates_tried,
        )

    # -------------------------------------------------------------------------
    # Balanced Corrective Double-Entry Voucher Draft
    # -------------------------------------------------------------------------
    # Post the EXPLAINED amount (matched_delta), not the full variance — a classifier that closes only
    # part of the variance must not draft a voucher for more than it actually explained.
    corrective_entry = _make_corrective_entry(
        line=line,
        root_cause=matched_cause,
        variance_paise=matched_delta,
        ref=ref_id,
        date_str=date_str,
        utr_str=utr_str,
    )
    reasoning_trace.append(
        f"Step 10: Drafted balanced corrective double-entry journal proposal ({corrective_entry['narration']})."
    )

    return Investigation(
        line_key=line.key,
        variance_paise=variance_paise,
        root_cause=matched_cause,
        confidence=confidence,
        reasoning_trace=reasoning_trace,
        corrective_entry=corrective_entry,
        candidates_tried=candidates_tried,
    )


def build_investigations(
    lines: list[BankCreditLine],
    attributions: list[RailAttribution],
    reconciliations: list[ReconciliationResult],
    recon_rows: list[ReconRow],
    index: ReconIndex,
    exceptions: list[ExceptionRecord],
) -> list[Investigation]:
    """Run root-cause investigation for all recon-failure exceptions."""
    lines_by_key = {ln.key: ln for ln in lines}
    attrs_by_key = {a.line_key: a for a in attributions}
    recons_by_key = {r.line_key: r for r in reconciliations}
    excs_by_key = {e.line_key: e for e in exceptions}

    # Focus on credits with reconciliation failures or unbalanced residuals
    target_keys: set[str] = set()
    for exc in exceptions:
        if exc.reason_code in (
            "unbalanced_residual",
            "partial_or_duplicate_settlement",
            "reconstructed_split_leg",
            "razorpay_coverage_not_found",
        ):
            target_keys.add(exc.line_key)

    investigations: list[Investigation] = []
    for line_key in sorted(target_keys):
        line = lines_by_key.get(line_key)
        if line is None:
            continue
        attr = attrs_by_key.get(line_key)
        rec = recons_by_key.get(line_key)
        exc = excs_by_key.get(line_key)

        inv = investigate(
            line=line,
            attribution=attr,
            reconciliation=rec,
            recon_rows=recon_rows,
            index=index,
            exception=exc,
        )
        investigations.append(inv)

    return investigations

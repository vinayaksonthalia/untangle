"""Active Recovery Controller (Feature 005 / spec-kit).

Turns abstention into an intelligent, ranked recovery plan. For every unresolved credit,
diagnoses why it could not be proven, enumerates what evidence would resolve it, groups
credits resolvable by the same action, and ranks recommended actions by expected
recoverable impact per unit cost.

Guarantees:
  1. Deterministic: stdlib-only, no LLM in the decision path.
  2. Additive: does NOT alter any attribution, reconciliation, fee-GST, or headline metrics.
  3. Read-only: no writes, no money movement, no feedback into attribution/reconciliation.
  4. Honest: amounts are framed "up to ₹X if confirmed", never "owed".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from engine.attribute import _SPLIT_DATE_WINDOW, _combine
from engine.evidence import narration_rail_signals, razorpay_signals
from engine.models import BankCreditLine, ExceptionRecord, Rail, RailAttribution

if TYPE_CHECKING:
    from engine.evidence import ReconIndex

# Blocking reason taxonomy (grounded in actual abstention reasons)
BLOCKING_BRAND_NO_TIE = "brand_no_tie"
BLOCKING_WEAK_UTR_SUFFIX = "weak_utr_suffix"
BLOCKING_AMBIGUOUS_SETSUM = "ambiguous_setsum"
BLOCKING_UNKNOWN_SENDER = "unknown_sender"
BLOCKING_LEDGER_EXCEPTION = "ledger_exception"
BLOCKING_RULE_CONFLICT = "rule_conflict"

# Action types & fixed operational costs
ACTION_EXPORT_SETTLEMENT_REPORT = "export_settlement_report"
ACTION_CONFIRM_UTR_WITH_BANK = "confirm_utr_with_bank"
ACTION_PROVIDE_SETTLEMENT_IDS = "provide_settlement_ids"
ACTION_CLASSIFY_COUNTERPARTY = "classify_counterparty"
ACTION_RECONCILE_ORDER_LEDGER = "reconcile_order_ledger"

ACTION_COSTS: dict[str, float] = {
    ACTION_EXPORT_SETTLEMENT_REPORT: 1.0,
    ACTION_CONFIRM_UTR_WITH_BANK: 2.0,
    ACTION_PROVIDE_SETTLEMENT_IDS: 1.5,
    ACTION_CLASSIFY_COUNTERPARTY: 0.5,
    ACTION_RECONCILE_ORDER_LEDGER: 1.0,
}

_RZP_SIGNAL_PREFIXES = ("utr", "amount_corr", "narration_brand", "ifsc", "settlement", "setsum")
# The REAL ledger-class reason codes the engine emits (engine/ledger.py, Feature 003). Verified against
# the codebase — do not add codes the engine never produces (uncredited_order was dropped in 003).
_LEDGER_EXCEPTION_CODES = {
    "ledger_mismatch",
    "duplicate_order_booking",
    "refund_not_reflected",
}


@dataclass(frozen=True)
class Hypothesis:
    """A competing candidate rail hypothesis for an unresolved bank credit."""

    line_key: str
    rail: str                 # the rail this credit MIGHT be (razorpay_settlement / other_gateway / ...)
    weight: float             # from the existing evidence scores (_combine); 0..1
    blocking_reason: str      # why it isn't proven (e.g. "brand_no_tie", "weak_utr_suffix", "unknown_sender")

    def to_dict(self) -> dict:
        return {
            "line_key": self.line_key,
            "rail": self.rail,
            "weight": round(self.weight, 4),
            "blocking_reason": self.blocking_reason,
        }


@dataclass(frozen=True)
class RecoveryAction:
    """A recommended next-best action that could resolve one or more credits."""

    action_type: str          # from the action taxonomy
    params: dict              # e.g. {"date_from": "...", "date_to": "..."}
    resolves: tuple[str, ...] # line_keys this action could resolve (sorted, deterministic)
    recoverable_paise: int    # SUM of amounts of `resolves` (bounded, honest "up to")
    cost: float               # fixed operational weight
    gain_per_cost: float      # recoverable_paise / cost (the ranking key)

    @property
    def description(self) -> str:
        """Human-readable action description framing recoverable amount honestly."""
        inr_str = f"₹{self.recoverable_paise / 100:,.2f}"
        n_credits = len(self.resolves)
        credit_plural = f"{n_credits} credit" if n_credits == 1 else f"{n_credits} credits"

        if self.action_type == ACTION_EXPORT_SETTLEMENT_REPORT:
            d_from = self.params.get("date_from", "")
            d_to = self.params.get("date_to", "")
            window = f" ({d_from} to {d_to})" if d_from and d_to else ""
            return (
                f"Export Razorpay settlement report{window} — "
                f"up to {inr_str} recoverable across {credit_plural} if confirmed"
            )
        if self.action_type == ACTION_CONFIRM_UTR_WITH_BANK:
            dt = self.params.get("date", "")
            dt_str = f" for {dt}" if dt else ""
            return (
                f"Confirm UTR with bank{dt_str} — "
                f"up to {inr_str} recoverable across {credit_plural} if confirmed"
            )
        if self.action_type == ACTION_PROVIDE_SETTLEMENT_IDS:
            dt = self.params.get("date", "")
            dt_str = f" for {dt}" if dt else ""
            return (
                f"Provide settlement IDs{dt_str} — "
                f"up to {inr_str} recoverable across {credit_plural} if confirmed"
            )
        if self.action_type == ACTION_CLASSIFY_COUNTERPARTY:
            dt = self.params.get("date", "")
            dt_str = f" for {dt}" if dt else ""
            return (
                f"Classify counterparty{dt_str} — "
                f"up to {inr_str} recoverable across {credit_plural} if confirmed"
            )
        if self.action_type == ACTION_RECONCILE_ORDER_LEDGER:
            return (
                f"Reconcile order ledger — "
                f"up to {inr_str} recoverable across {credit_plural} if confirmed"
            )
        return (
            f"Action {self.action_type} — "
            f"up to {inr_str} recoverable across {credit_plural} if confirmed"
        )

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "params": dict(self.params),
            "resolves": list(self.resolves),
            "recoverable_paise": self.recoverable_paise,
            "cost": self.cost,
            "gain_per_cost": round(self.gain_per_cost, 4),
            "description": self.description,
        }


@dataclass(frozen=True)
class RecoveryPlan:
    """A ranked plan of next-best recovery actions."""

    actions: tuple[RecoveryAction, ...]   # ranked, highest gain_per_cost first (deterministic tie-break)
    unresolved_count: int
    unresolved_paise: int
    recoverable_if_actioned_paise: int    # sum over distinct resolvable credits (no double counting)
    note: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "actions": [a.to_dict() for a in self.actions],
            "unresolved_count": self.unresolved_count,
            "unresolved_paise": self.unresolved_paise,
            "recoverable_if_actioned_paise": self.recoverable_if_actioned_paise,
        }
        if self.note:
            d["note"] = self.note
        return d


def _derive_blocking_reason(
    line: BankCreditLine,
    attribution: RailAttribution,
    index: ReconIndex,
    exception: ExceptionRecord | None,
) -> str:
    """Deterministically derive the blocking reason for an unresolved credit."""
    # 1. Rule conflict
    if (exception is not None and exception.reason_code == "rule_conflict") or any(
        e.signal == "rule_conflict" for e in attribution.evidence
    ):
        return BLOCKING_RULE_CONFLICT

    # 2. Ambiguous set-sum
    if (exception is not None and exception.reason_code == "multiple_satisfying_subsets") or any(
        e.signal == "multiple_satisfying_subsets" for e in attribution.evidence
    ):
        return BLOCKING_AMBIGUOUS_SETSUM

    # 3. Ledger exceptions
    if exception is not None and exception.reason_code in _LEDGER_EXCEPTION_CODES:
        return BLOCKING_LEDGER_EXCEPTION

    # 4. Razorpay-leaning signals
    rzp_ev = razorpay_signals(line, index)
    all_rzp_signals = {e.signal for e in rzp_ev} | {
        e.signal for e in attribution.evidence
        if e.signal.startswith(_RZP_SIGNAL_PREFIXES) or e.signal in {"split_reconstruction", "utr_suffix_weak"}
    }

    if "utr_suffix_weak" in all_rzp_signals and not any(
        s in {"utr_exact", "utr_suffix"} for s in all_rzp_signals
    ):
        return BLOCKING_WEAK_UTR_SUFFIX

    if (
        bool(all_rzp_signals & {"narration_brand_rzp", "settlement_ref", "ifsc_ratn"})
        or (exception is not None and exception.reason_code == "razorpay_uncertain")
        or any(e.signal.startswith(_RZP_SIGNAL_PREFIXES) for e in attribution.evidence)
    ):
        return BLOCKING_BRAND_NO_TIE

    # 5. Default: unknown sender / unattributed ambiguous
    return BLOCKING_UNKNOWN_SENDER


def diagnose(
    line: BankCreditLine,
    attribution: RailAttribution,
    index: ReconIndex,
    exception: ExceptionRecord | None = None,
) -> list[Hypothesis]:
    """Diagnose why an unresolved credit could not be proven and enumerate competing hypotheses.

    Pure function: deterministic, reads only inputs, does not mutate anything.
    Weights are derived using the existing `_combine` correlation-aware scoring.
    """
    blocking = _derive_blocking_reason(line, attribution, index, exception)
    hypotheses: list[Hypothesis] = []

    # 1. Razorpay hypothesis
    if attribution.rail == Rail.RAZORPAY_SETTLEMENT.value:
        hypotheses.append(
            Hypothesis(
                line_key=line.key,
                rail=Rail.RAZORPAY_SETTLEMENT.value,
                weight=round(attribution.confidence, 4),
                blocking_reason=blocking,
            )
        )
    else:
        rzp_ev = razorpay_signals(line, index)
        rzp_items = list(rzp_ev)
        for e in attribution.evidence:
            if e not in rzp_items and (
                e.signal.startswith(_RZP_SIGNAL_PREFIXES)
                or e.signal in {"multiple_satisfying_subsets", "split_reconstruction"}
            ):
                rzp_items.append(e)
        if rzp_items:
            w = _combine(rzp_items)
            if w > 0.0:
                hypotheses.append(
                    Hypothesis(
                        line_key=line.key,
                        rail=Rail.RAZORPAY_SETTLEMENT.value,
                        weight=round(w, 4),
                        blocking_reason=blocking,
                    )
                )

    # 2. Competing non-Razorpay rail hypotheses
    non_rzp = narration_rail_signals(line)
    for rail, items in non_rzp.items():
        if items:
            w = _combine(items)
            if w > 0.0:
                hypotheses.append(
                    Hypothesis(
                        line_key=line.key,
                        rail=rail.value,
                        weight=round(w, 4),
                        blocking_reason=blocking,
                    )
                )

    if attribution.rail not in {Rail.UNKNOWN.value, Rail.RAZORPAY_SETTLEMENT.value}:
        if not any(h.rail == attribution.rail for h in hypotheses):
            hypotheses.append(
                Hypothesis(
                    line_key=line.key,
                    rail=attribution.rail,
                    weight=round(attribution.confidence, 4),
                    blocking_reason=blocking,
                )
            )

    # 3. Fallback when no signals exist
    if not hypotheses:
        hypotheses.append(
            Hypothesis(
                line_key=line.key,
                rail=Rail.UNKNOWN.value,
                weight=0.0,
                blocking_reason=blocking,
            )
        )

    # Sort deterministically: highest weight first, then rail ascending
    hypotheses.sort(key=lambda h: (-h.weight, h.rail))
    return hypotheses


def _map_blocking_to_action(
    line: BankCreditLine,
    blocking_reason: str,
    exception: ExceptionRecord | None,
) -> tuple[str, dict[str, Any], float]:
    """Map derived blocking_reason to (action_type, params, cost) per §3 taxonomy."""
    if blocking_reason == BLOCKING_BRAND_NO_TIE:
        d_from = (line.value_date - timedelta(days=_SPLIT_DATE_WINDOW)).isoformat()
        d_to = (line.value_date + timedelta(days=_SPLIT_DATE_WINDOW)).isoformat()
        return (
            ACTION_EXPORT_SETTLEMENT_REPORT,
            {"date_from": d_from, "date_to": d_to},
            ACTION_COSTS[ACTION_EXPORT_SETTLEMENT_REPORT],
        )

    if blocking_reason == BLOCKING_WEAK_UTR_SUFFIX:
        return (
            ACTION_CONFIRM_UTR_WITH_BANK,
            {"date": line.value_date.isoformat(), "amount_paise": line.amount_paise},
            ACTION_COSTS[ACTION_CONFIRM_UTR_WITH_BANK],
        )

    if blocking_reason == BLOCKING_AMBIGUOUS_SETSUM:
        return (
            ACTION_PROVIDE_SETTLEMENT_IDS,
            {"date": line.value_date.isoformat(), "amount_paise": line.amount_paise},
            ACTION_COSTS[ACTION_PROVIDE_SETTLEMENT_IDS],
        )

    if blocking_reason in {BLOCKING_UNKNOWN_SENDER, BLOCKING_RULE_CONFLICT}:
        params: dict[str, Any] = {
            "date": line.value_date.isoformat(),
            "amount_paise": line.amount_paise,
        }
        if line.bank_ref:
            params["bank_ref"] = line.bank_ref
        return (
            ACTION_CLASSIFY_COUNTERPARTY,
            params,
            ACTION_COSTS[ACTION_CLASSIFY_COUNTERPARTY],
        )

    if blocking_reason == BLOCKING_LEDGER_EXCEPTION:
        return (
            ACTION_RECONCILE_ORDER_LEDGER,
            {"date": line.value_date.isoformat(), "amount_paise": line.amount_paise},
            ACTION_COSTS[ACTION_RECONCILE_ORDER_LEDGER],
        )

    # Fallback default
    return (
        ACTION_CLASSIFY_COUNTERPARTY,
        {"date": line.value_date.isoformat(), "amount_paise": line.amount_paise},
        ACTION_COSTS[ACTION_CLASSIFY_COUNTERPARTY],
    )


def build_recovery_plan(
    lines: list[BankCreditLine],
    attributions: list[RailAttribution],
    index: ReconIndex,
    exceptions: list[ExceptionRecord],
    *,
    max_actions: int = 20,
) -> RecoveryPlan:
    """Build a ranked, deduplicated plan of next-best recovery actions.

    Pure function: deterministic, reads only inputs, does not mutate anything.
    Amounts are framed honestly as "up to ₹X if confirmed".
    """
    lines_by_key = {ln.key: ln for ln in lines}
    attrs_by_key = {a.line_key: a for a in attributions}
    excs_by_key = {e.line_key: e for e in exceptions}

    # Find unresolved credits: credits with an exception or with UNKNOWN/abstained attribution
    unresolved_lines: list[BankCreditLine] = []
    seen_keys: set[str] = set()
    for line in lines:
        is_unresolved = (
            line.key in excs_by_key
            or (line.key in attrs_by_key and (
                attrs_by_key[line.key].abstained
                or attrs_by_key[line.key].rail == Rail.UNKNOWN.value
            ))
        )
        if is_unresolved and line.key not in seen_keys:
            unresolved_lines.append(line)
            seen_keys.add(line.key)

    unresolved_count = len(unresolved_lines)
    unresolved_paise = sum(ln.amount_paise for ln in unresolved_lines)

    if not unresolved_lines:
        return RecoveryPlan(
            actions=(),
            unresolved_count=0,
            unresolved_paise=0,
            recoverable_if_actioned_paise=0,
            note=None,
        )

    # Group identical actions (same action_type + params)
    # group_key -> (action_type, params, cost, list_of_line_keys, list_of_amounts)
    groups: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {}

    for line in unresolved_lines:
        attr = attrs_by_key.get(
            line.key,
            RailAttribution(line.key, Rail.UNKNOWN.value, 0.0, "none", [], abstained=True),
        )
        exc = excs_by_key.get(line.key)
        blocking = _derive_blocking_reason(line, attr, index, exc)
        act_type, params, cost = _map_blocking_to_action(line, blocking, exc)

        param_items = tuple(sorted(params.items()))
        g_key = (act_type, param_items)

        if g_key not in groups:
            groups[g_key] = {
                "action_type": act_type,
                "params": params,
                "cost": cost,
                "keys": [],
                "amounts": [],
            }
        groups[g_key]["keys"].append(line.key)
        groups[g_key]["amounts"].append(line.amount_paise)

    # Construct RecoveryAction for each group
    actions: list[RecoveryAction] = []
    for g in groups.values():
        resolves = tuple(sorted(set(g["keys"])))
        rec_paise = sum(g["amounts"])
        cost = g["cost"]
        gain_per_cost = rec_paise / cost if cost > 0 else 0.0
        actions.append(
            RecoveryAction(
                action_type=g["action_type"],
                params=g["params"],
                resolves=resolves,
                recoverable_paise=rec_paise,
                cost=cost,
                gain_per_cost=gain_per_cost,
            )
        )

    # Rank actions: gain_per_cost desc, recoverable_paise desc, action_type asc, resolves asc
    actions.sort(key=lambda a: (-a.gain_per_cost, -a.recoverable_paise, a.action_type, a.resolves))

    # Cap at max_actions
    note: str | None = None
    if len(actions) > max_actions:
        total_actions = len(actions)
        actions = actions[:max_actions]
        note = (
            f"Plan capped at top {max_actions} actions (of {total_actions} available) "
            "ranked by expected impact per cost."
        )

    # Compute recoverable_if_actioned_paise counting each credit ONCE (set union)
    actioned_keys: set[str] = set()
    for a in actions:
        actioned_keys.update(a.resolves)
    recoverable_if_actioned_paise = sum(
        lines_by_key[k].amount_paise for k in actioned_keys if k in lines_by_key
    )

    return RecoveryPlan(
        actions=tuple(actions),
        unresolved_count=unresolved_count,
        unresolved_paise=unresolved_paise,
        recoverable_if_actioned_paise=recoverable_if_actioned_paise,
        note=note,
    )

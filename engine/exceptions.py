"""Honest exception list (spec FR-009, US3).

Every bank credit the engine could not confidently attribute, or could attribute to
Razorpay but not reconcile, becomes an exception with a taxonomy-aligned reason code and a
concrete suggested action. Nothing is force-matched: an unresolved credit is surfaced for a
human, never guessed. A short, well-explained exception list is the honest counterpart to
the high-precision auto-attributions.

Reason codes (aligned to EXCEPTION_TAXONOMY.md):
- ``unattributed_ambiguous``      — abstained with no Razorpay-leaning signal at all.
- ``razorpay_uncertain``          — abstained but carried some Razorpay signal below τ.
- ``razorpay_coverage_not_found`` — attributed Razorpay, but no exact settlement coverage
                                    (split leg / partial / carry-forward the engine bounded out of).
- ``rule_conflict``               — two approved rules disagree on the rail; abstained (a human
                                    must retire/correct one rule, not add another pattern).
"""

from __future__ import annotations

from engine.models import BankCreditLine, ExceptionRecord, Rail, RailAttribution

_RZP_SIGNAL_PREFIXES = ("utr", "amount_corr", "narration_brand", "ifsc", "settlement", "setsum")


def _amount_str(line: BankCreditLine | None) -> str:
    if line is None:
        return "unknown amount"
    return f"₹{line.amount_paise / 100:,.2f} on {line.value_date.isoformat()}"


def build_exceptions(
    attributions: list[RailAttribution],
    unresolved_rzp: list[str],
    lines_by_key: dict[str, BankCreditLine],
    ambiguous_rzp: set[str] | None = None,
    duplicate_or_split_rzp: set[str] | None = None,
    unbalanced_rzp: dict[str, int] | None = None,
) -> list[ExceptionRecord]:
    unresolved = set(unresolved_rzp)
    ambiguous = set(ambiguous_rzp or ())
    duplicate_or_split = set(duplicate_or_split_rzp or ())
    unbalanced = dict(unbalanced_rzp or {})
    out: list[ExceptionRecord] = []
    for a in attributions:
        line = lines_by_key.get(a.line_key)
        ev = list(a.evidence)
        if a.abstained or a.rail == Rail.UNKNOWN.value:
            if any(e.signal == "rule_conflict" for e in a.evidence):
                detail = next((e.detail for e in a.evidence if e.signal == "rule_conflict"), "")
                out.append(ExceptionRecord(
                    a.line_key, "rule_conflict",
                    f"{_amount_str(line)}: contradictory approved rules target different rails "
                    f"({detail}) — abstained rather than force a pick.",
                    "Human review: two approved rules disagree on this line's rail. Retire or "
                    "correct one of the conflicting rules; do NOT add another narration pattern.",
                    evidence=ev,
                ))
            elif any(e.signal == "multiple_satisfying_subsets" for e in a.evidence):
                out.append(ExceptionRecord(
                    a.line_key, "multiple_satisfying_subsets",
                    f"{_amount_str(line)}: ambiguous set-sum — multiple distinct settlement subsets sum to this amount.",
                    "Human review: multiple distinct settlement combinations match this amount; verify manually before booking.",
                    evidence=ev,
                ))
            else:
                leaning = any(e.signal.startswith(_RZP_SIGNAL_PREFIXES) for e in a.evidence)
                if leaning:
                    out.append(ExceptionRecord(
                        a.line_key, "razorpay_uncertain",
                        f"{_amount_str(line)}: partial Razorpay signal but below the confidence "
                        f"threshold ({a.confidence:.2f}).",
                        "Human review: likely Razorpay but not provable — confirm against the "
                        "settlement report before booking.",
                        evidence=ev,
                    ))
                else:
                    out.append(ExceptionRecord(
                        a.line_key, "unattributed_ambiguous",
                        f"{_amount_str(line)}: no distinctive rail signal in the narration.",
                        "Human review: assign the rail manually; consider adding its narration "
                        "pattern to the rules.",
                        evidence=ev,
                    ))
        elif a.line_key in unresolved:
            if a.line_key in ambiguous:
                out.append(ExceptionRecord(
                    a.line_key, "multiple_satisfying_subsets",
                    f"{_amount_str(line)}: attributed Razorpay, but multiple distinct settlement subsets satisfy this amount.",
                    "Human review: ambiguous set-sum in settlement report; match against the settlement report by hand.",
                    evidence=ev,
                ))
            elif a.line_key in duplicate_or_split:
                out.append(ExceptionRecord(
                    a.line_key, "partial_or_duplicate_settlement",
                    f"{_amount_str(line)}: settlement is split across multiple bank credits or partially credited (FR-016). Will not net together to force balance.",
                    "Human review: partial or duplicate settlement; verify per-leg bank credits against settlement report.",
                    evidence=ev,
                ))
            elif a.line_key in unbalanced:
                res_paise = unbalanced[a.line_key]
                out.append(ExceptionRecord(
                    a.line_key, "unbalanced_residual",
                    f"{_amount_str(line)}: unbalanced reconciliation — candidate settlement net differs by ₹{abs(res_paise)/100:,.2f}. No balancing entry forced.",
                    "Human review: inspect residual discrepancy between bank statement and settlement report.",
                    evidence=ev,
                ))
            elif any(e.signal == "split_reconstruction" for e in a.evidence):
                detail = next((e.detail for e in a.evidence if e.signal == "split_reconstruction"), "")
                out.append(ExceptionRecord(
                    a.line_key, "reconstructed_split_leg",
                    f"{_amount_str(line)}: reconstructed split-settlement leg — {detail}. Attributed "
                    "Razorpay because its group uniquely sums to a real settlement net; per-leg "
                    "entity-level reconciliation is pending.",
                    "Human review: confirm the leg group against the settlement report; the amounts "
                    "balance to the settlement net to the paise.",
                    evidence=ev,
                ))
            else:
                out.append(ExceptionRecord(
                    a.line_key, "razorpay_coverage_not_found",
                    f"{_amount_str(line)}: attributed Razorpay, but no exact settlement coverage "
                    "was found within bounds.",
                    "Human review: likely a split leg, partial settlement, or carry-forward — "
                    "match against the settlement report by hand.",
                    evidence=ev,
                ))
    return out

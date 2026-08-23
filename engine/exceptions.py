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
) -> list[ExceptionRecord]:
    unresolved = set(unresolved_rzp)
    out: list[ExceptionRecord] = []
    for a in attributions:
        line = lines_by_key.get(a.line_key)
        if a.abstained or a.rail == Rail.UNKNOWN.value:
            leaning = any(e.signal.startswith(_RZP_SIGNAL_PREFIXES) for e in a.evidence)
            if leaning:
                out.append(ExceptionRecord(
                    a.line_key, "razorpay_uncertain",
                    f"{_amount_str(line)}: partial Razorpay signal but below the confidence "
                    f"threshold ({a.confidence:.2f}).",
                    "Human review: likely Razorpay but not provable — confirm against the "
                    "settlement report before booking.",
                ))
            else:
                out.append(ExceptionRecord(
                    a.line_key, "unattributed_ambiguous",
                    f"{_amount_str(line)}: no distinctive rail signal in the narration.",
                    "Human review: assign the rail manually; consider adding its narration "
                    "pattern to the rules.",
                ))
        elif a.line_key in unresolved:
            out.append(ExceptionRecord(
                a.line_key, "razorpay_coverage_not_found",
                f"{_amount_str(line)}: attributed Razorpay, but no exact settlement coverage "
                "was found within bounds.",
                "Human review: likely a split leg, partial settlement, or carry-forward — "
                "match against the settlement report by hand.",
            ))
    return out

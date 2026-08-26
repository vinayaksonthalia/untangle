"""Human-proposed rules module (G5 / FR-009 / G6).

Guarantees:
  1. G5 — Proposed, never self-applied: a proposed rule does NOTHING until explicitly
     approved by a human. The deterministic core is never modified.
  2. G6 — Derived metadata only: rules store only normalized pattern tokens (e.g. keywords),
     never raw statements, PII, amounts, or verbatim bank rows.
  3. Strict matching: near-matches or partial token collisions stay exceptions (never lowers precision).
  4. Traceability: rule-derived attributions are marked tier='rule_derived' and trace
     directly to the approving human.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from engine.models import BankCreditLine, EvidenceItem, Rail, RailAttribution, Tier


@dataclass(frozen=True)
class ProposedRule:
    """A durable, versioned rule proposed upon human exception resolution."""

    rule_id: str
    version: int
    target_rail: str
    pattern_type: str            # e.g. "narration_keyword", "bank_ref_prefix"
    pattern_value: str           # derived metadata ONLY (G6 — no raw statements)
    created_at: str
    proposed_by: str = "system"
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ProposedRule:
        return cls(**data)


def propose_rule(
    target_rail: str,
    pattern_value: str,
    pattern_type: str = "narration_keyword",
    rationale: str = "",
    proposed_by: str = "system",
    rule_id: str | None = None,
    version: int = 1,
) -> ProposedRule:
    """Propose a new rule from a human resolution.

    The returned rule is INERT (approved=False, approved_by=None).
    It stores only derived metadata (pattern_value) to respect G6.
    """
    cleaned_pattern = pattern_value.strip().lower()
    if not cleaned_pattern:
        raise ValueError("Pattern value cannot be empty")
    valid_rails = {r.value for r in Rail if r != Rail.UNKNOWN}
    if target_rail not in valid_rails:
        raise ValueError(f"Invalid target rail: {target_rail}. Must be one of {valid_rails}")

    rid = rule_id or f"rule_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    return ProposedRule(
        rule_id=rid,
        version=version,
        target_rail=target_rail,
        pattern_type=pattern_type,
        pattern_value=cleaned_pattern,
        created_at=now,
        proposed_by=proposed_by,
        approved=False,
        approved_by=None,
        approved_at=None,
        rationale=rationale,
    )


def approve_rule(rule: ProposedRule, approver: str) -> ProposedRule:
    """Explicitly approve a proposed rule (G5).

    Only after this call can the rule be applied in attribution.
    """
    if not approver or not approver.strip():
        raise ValueError("Approver identifier must be provided")
    now = datetime.now(timezone.utc).isoformat()
    # Immutable: approval returns a NEW frozen rule; an approved rule cannot be mutated
    # after the fact (e.g. its target_rail retargeted) — the approval is a fixed record.
    return replace(rule, approved=True, approved_by=approver.strip(), approved_at=now)


def match_rule(line: BankCreditLine, rule: ProposedRule) -> bool:
    """Check if an APPROVED rule strictly matches a line.

    Unapproved rules NEVER match (inertness).
    Near-matches do NOT match (preserves precision bar).
    """
    if not rule.approved:
        return False

    text = line.raw_text().lower()
    pattern = rule.pattern_value.lower()

    if rule.pattern_type == "narration_keyword":
        escaped = re.escape(pattern)
        regex = rf"(?:^|[\s\-_/]){escaped}(?:$|[\s\-_/])"
        return bool(re.search(regex, text))

    if rule.pattern_type == "bank_ref_prefix":
        if line.bank_ref:
            return line.bank_ref.lower().startswith(pattern)
        return False

    # Unknown pattern_type: do NOT fall back to a loose substring match (that would let a
    # short pattern fire inside an unrelated word and lower the precision bar). Only the
    # explicit, boundary-safe pattern types above may match.
    return False


def apply_approved_rules(
    lines: list[BankCreditLine],
    rules: list[ProposedRule],
) -> dict[str, RailAttribution]:
    """Apply approved rules to lines, returning attributions for matching lines.

    Unapproved rules are strictly ignored (G5).
    Resulting attributions are marked Tier.RULE ('rule_derived') and cite the approver.
    """
    out: dict[str, RailAttribution] = {}
    approved = [r for r in rules if r.approved]
    if not approved:
        return out

    for line in lines:
        # FR-015: a debit is never an inbound credit — an approved rule (which can target any
        # rail, including razorpay_settlement) must never reclassify a debit into a credit rail.
        if not line.is_credit:
            continue
        # Collect ALL matching approved rules (deterministic order by rule_id), not just the
        # first: order must never change the verdict. If matching rules disagree on the target
        # rail, that is a human-approval conflict — do NOT force a pick; leave the line abstained.
        matched = sorted((r for r in approved if match_rule(line, r)), key=lambda r: r.rule_id)
        if not matched:
            continue
        conflicting_rails = {r.target_rail for r in matched}
        if len(conflicting_rails) > 1:
            # Conflicting approvals → abstain rather than force a rail. Emit an EXPLICIT
            # abstention marker (not a silent omission): a human-approval conflict is the
            # strongest "this line is contested" signal, and attribute_all uses this marker
            # to override a soft base guess (Tier B/C/LLM). It never overrides Tier A, since
            # a clean UTR-exact identifier tie is machine fact, not a human opinion.
            out[line.key] = RailAttribution(
                line_key=line.key,
                rail=Rail.UNKNOWN.value,
                confidence=0.0,
                tier=Tier.NONE.value,
                evidence=[
                    EvidenceItem(
                        signal="rule_conflict",
                        detail=(
                            "conflicting approved rules target "
                            f"{sorted(conflicting_rails)}: {sorted(r.rule_id for r in matched)}"
                        ),
                        weight=0.0,
                    )
                ],
                abstained=True,
            )
            continue
        rule = matched[0]
        evidence = [
            EvidenceItem(
                signal="human_approved_rule",
                detail=f"Matched rule {rule.rule_id} (pattern '{rule.pattern_value}') approved by {rule.approved_by}",
                weight=0.95,
            )
        ]
        out[line.key] = RailAttribution(
            line_key=line.key,
            rail=rule.target_rail,
            confidence=0.95,
            tier=Tier.RULE.value,
            evidence=evidence,
            abstained=False,
        )
    return out

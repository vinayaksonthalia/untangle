"""Advisory Agent Evidence Service for tenant reconciliation queries.

Untangle is a read-only finance controller. This service answers factual questions
over bounded AgentEvidenceSnapshot data. It strictly refuses any mutating intent
(moving money, approving journals, certifying closes, or changing financial state)
and abstains when queries are unsupported or ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.repositories import (
    get_certificate_by_run_id,
    get_result_by_run_id,
    get_run_by_public_id,
    list_investigations_by_run_id,
)

ADVISORY_NOTICE = (
    "Untangle AI agent responses are advisory only. Calculations, attributions, "
    "journals, and certificates are deterministic and verifiable in the canonical report."
)

MUTATING_INTENT_PATTERNS = (
    r"\b(?:approve|post)\s+(?:(?:the|a|an|this|that|all)\s+)*(?:journal|voucher|entry|ledger)\b",
    r"\b(?:certify|sign)\s+(?:(?:the|a|an|this|that|all)\s+)*(?:close|period|certificate)\b",
    r"\b(?:transfer|move|send|pay|refund|disburse)\s+(?:(?:the|a|an|this|that|all)\s+)*(?:money|funds|amount|paise|inr)\b",
    r"\b(?:override|force|change|alter|modify)\s+(?:(?:the|a|an|this|that|all)\s+)*(?:reconciliation|match|status|verdict|decision)\b",
    r"\b(?:delete|drop|purge|truncate)\s+(?:(?:the|a|an|this|that|all)\s+)*(?:run|organisation|tenant|database)\b",
)

MUTATING_REFUSAL_REASON = (
    "Untangle is a read-only finance controller. The agent service cannot move money, "
    "approve journals, certify closes, change ledger entries, or override reconciliation decisions."
)


@dataclass(frozen=True)
class AgentEvidenceSnapshot:
    """Bounded, read-only snapshot of authoritative financial evidence for a run."""

    run_id: str
    status: str
    reporting_period_start: str | None
    reporting_period_end: str | None
    reconciliation_hash: str | None
    engine_version: str | None
    rule_pack_id: str | None
    bank_adapter_id: str | None
    summary: dict[str, Any]
    rails: list[dict[str, Any]]
    root_causes: list[dict[str, Any]]
    certificate: dict[str, Any] | None

    @classmethod
    def load(
        cls, session: Session, context: TenantContext, run_public_id: str
    ) -> AgentEvidenceSnapshot | None:
        """Load an authoritative evidence snapshot from persistent storage within tenant scope."""
        run = get_run_by_public_id(session, context, run_public_id)
        if run is None or run.is_deleted:
            return None

        result = get_result_by_run_id(session, context, run.id)
        pres = (result.presentation_json if result else {}) or {}

        cert_record = get_certificate_by_run_id(session, context, run.id)
        cert_data = None
        if cert_record:
            cert_data = {
                "certificate_id": cert_record.public_id,
                "is_signed": cert_record.is_signed,
                "content_sha256": cert_record.content_sha256,
                "report_sha256": cert_record.report_sha256,
            }

        inv_records = list_investigations_by_run_id(session, context, run.id)
        root_causes = [
            {
                "line_key": inv.line_key,
                "root_cause": inv.root_cause,
                "resolved": inv.resolved,
                "variance_paise": inv.variance_paise,
                "confidence": inv.confidence,
            }
            for inv in inv_records
        ]

        return cls(
            run_id=run.public_id,
            status=run.status,
            reporting_period_start=(
                run.reporting_period_start.isoformat() if run.reporting_period_start else None
            ),
            reporting_period_end=(
                run.reporting_period_end.isoformat() if run.reporting_period_end else None
            ),
            reconciliation_hash=run.reconciliation_hash,
            engine_version=run.engine_version,
            rule_pack_id=run.rule_pack_id,
            bank_adapter_id=run.bank_adapter_id,
            summary=pres.get("summary") or {},
            rails=pres.get("rails") or [],
            root_causes=root_causes,
            certificate=cert_data,
        )


def _format_inr(paise: int) -> str:
    """Format integer paise as human-readable INR string without floats."""
    sign = "-" if paise < 0 else ""
    abs_paise = abs(paise)
    rupees = abs_paise // 100
    remainder = abs_paise % 100
    return f"{sign}₹{rupees:,}.{remainder:02d}"


def resolve_agent_query(snapshot: AgentEvidenceSnapshot, query: str) -> dict[str, Any]:
    """Deterministically resolve a user query against the evidence snapshot."""
    clean_query = query.strip()
    lowered = clean_query.lower()

    # 1. Mutating Intent Check (Fail immediately with explicit refusal)
    for pattern in MUTATING_INTENT_PATTERNS:
        if re.search(pattern, lowered):
            return {
                "query": clean_query,
                "run_id": snapshot.run_id,
                "status": "refused",
                "intent": "mutating_financial_action",
                "answer": None,
                "refusal_reason": MUTATING_REFUSAL_REASON,
                "evidence": {},
                "advisory_notice": ADVISORY_NOTICE,
            }

    # 2. Reconciled / Totals / Headline queries
    if any(
        k in lowered for k in ("reconciled", "total", "credit", "headline", "unresolved", "summary")
    ):
        s = snapshot.summary
        rec_paise = s.get("reconciled_paise", 0)
        unres_paise = s.get("unresolved_paise", 0)
        tot_credit = s.get("total_credit_paise", 0)
        rec_count = s.get("reconciled_count", 0)
        unres_count = s.get("unresolved_count", 0)

        answer = (
            f"In run {snapshot.run_id}, total credit is {_format_inr(tot_credit)} ({tot_credit} paise). "
            f"Reconciled: {_format_inr(rec_paise)} ({rec_paise} paise) across {rec_count} settlements. "
            f"Unresolved: {_format_inr(unres_paise)} ({unres_paise} paise) across {unres_count} settlements."
        )
        return {
            "query": clean_query,
            "run_id": snapshot.run_id,
            "status": "answered",
            "intent": "reconciliation_summary",
            "answer": answer,
            "refusal_reason": None,
            "evidence": {
                "total_credit_paise": tot_credit,
                "reconciled_paise": rec_paise,
                "reconciled_count": rec_count,
                "unresolved_paise": unres_paise,
                "unresolved_count": unres_count,
            },
            "advisory_notice": ADVISORY_NOTICE,
        }

    # 3. Recoverable Fees / GST Drift queries
    if any(k in lowered for k in ("fee", "gst", "recoverable", "drift", "charges")):
        fee_paise = snapshot.summary.get("fee_gst_recoverable_paise", 0)
        answer = (
            f"Recoverable fee and GST variance for run {snapshot.run_id} is "
            f"{_format_inr(fee_paise)} ({fee_paise} paise)."
        )
        return {
            "query": clean_query,
            "run_id": snapshot.run_id,
            "status": "answered",
            "intent": "fee_recoverable_inquiry",
            "answer": answer,
            "refusal_reason": None,
            "evidence": {"fee_gst_recoverable_paise": fee_paise},
            "advisory_notice": ADVISORY_NOTICE,
        }

    # 4. Root Causes & Variance Investigations queries
    if any(k in lowered for k in ("root cause", "variance", "investigation", "why", "exceptions")):
        rc_list = snapshot.root_causes
        total = len(rc_list)
        resolved = sum(1 for c in rc_list if c["resolved"])
        causes_summary = {}
        for c in rc_list:
            causes_summary[c["root_cause"]] = causes_summary.get(c["root_cause"], 0) + 1

        answer = (
            f"Run {snapshot.run_id} has {total} investigation cases ({resolved} resolved, "
            f"{total - resolved} abstained). Breakdown by root cause: {causes_summary}."
        )
        return {
            "query": clean_query,
            "run_id": snapshot.run_id,
            "status": "answered",
            "intent": "investigations_breakdown",
            "answer": answer,
            "refusal_reason": None,
            "evidence": {
                "total_cases": total,
                "resolved_cases": resolved,
                "abstained_cases": total - resolved,
                "root_cause_counts": causes_summary,
            },
            "advisory_notice": ADVISORY_NOTICE,
        }

    # 5. Certificate & Close queries
    if any(k in lowered for k in ("certificate", "certified", "signed", "close", "audit")):
        cert = snapshot.certificate
        if cert:
            answer = (
                f"Run {snapshot.run_id} close certificate is issued (ID: {cert['certificate_id']}). "
                f"Signed: {cert['is_signed']}. Content SHA-256: {cert['content_sha256']}."
            )
        else:
            answer = f"Run {snapshot.run_id} does not have an issued close certificate."

        return {
            "query": clean_query,
            "run_id": snapshot.run_id,
            "status": "answered",
            "intent": "certificate_inquiry",
            "answer": answer,
            "refusal_reason": None,
            "evidence": cert or {},
            "advisory_notice": ADVISORY_NOTICE,
        }

    # 6. Rails Distribution queries
    if any(k in lowered for k in ("rail", "upi", "gateway", "distribution", "breakdown")):
        rails_info = [
            f"{r.get('label')}: {_format_inr(r.get('amount_paise', 0))} ({r.get('count', 0)} txns)"
            for r in snapshot.rails
        ]
        answer = f"Rail distribution for run {snapshot.run_id}: " + "; ".join(rails_info)
        return {
            "query": clean_query,
            "run_id": snapshot.run_id,
            "status": "answered",
            "intent": "rails_breakdown",
            "answer": answer,
            "refusal_reason": None,
            "evidence": {"rails": snapshot.rails},
            "advisory_notice": ADVISORY_NOTICE,
        }

    # 7. Unsupported / Ambiguous query -> Explicit Abstention
    return {
        "query": clean_query,
        "run_id": snapshot.run_id,
        "status": "abstained",
        "intent": "unsupported_or_ambiguous",
        "answer": "Unsupported query or insufficient evidence in the current run snapshot to determine answer deterministically.",
        "refusal_reason": None,
        "evidence": {},
        "advisory_notice": ADVISORY_NOTICE,
    }

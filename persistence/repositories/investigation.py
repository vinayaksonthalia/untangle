"""Investigation repository.

Stores and queries root-cause investigation records for reconciliation variances.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_INVESTIGATION, generate_public_id
from persistence.models import InvestigationRecord
from persistence.repositories.base import scoped_select
from persistence.uow import insert_with_public_id_retry


def save_investigations(
    session: Session,
    context: TenantContext,
    run_id: int,
    cases: list[dict[str, Any]],
) -> list[InvestigationRecord]:
    """Persist a list of investigation cases bound to a run."""
    records: list[InvestigationRecord] = []
    for c in cases:
        record = insert_with_public_id_retry(
            session,
            lambda c=c: InvestigationRecord(
                public_id=generate_public_id(PREFIX_INVESTIGATION),
                organisation_id=context.organisation_id,
                run_id=run_id,
                line_key=c["line_key"],
                root_cause=c["root_cause"],
                resolved=bool(c.get("resolved", False)),
                confidence=float(c.get("confidence", 0.0)),
                variance_paise=int(c.get("variance_paise", 0)),
                details_json=c.get("details_json") or c,
            ),
            expected_constraint="investigations_public_id_key",
        )
        records.append(record)
    return records


def list_investigations_by_run_id(
    session: Session, context: TenantContext, run_id: int
) -> list[InvestigationRecord]:
    """List all investigation records for a specific run within the tenant scope."""
    stmt = scoped_select(InvestigationRecord, context).where(InvestigationRecord.run_id == run_id)
    return list(session.scalars(stmt).all())

"""Reconciliation result repository.

Stores canonical report text, queryable JSON projections, and SHA-256 digests.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_RESULT, generate_public_id
from persistence.models import ReconciliationResult
from persistence.repositories.base import scoped_select
from persistence.uow import insert_with_public_id_retry


class ResultIntegrityError(ValueError):
    """Raised when canonical result digest does not match the report text."""


def save_result(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    summary_json: dict[str, Any],
    presentation_json: dict[str, Any],
    canonical_report_text: str,
    audit_root: str,
    report_sha256: str,
) -> ReconciliationResult:
    """Persist a canonical reconciliation result bound to a run.

    Verifies that the provided report_sha256 strictly equals the SHA-256 of the
    exact canonical_report_text before insertion.
    """
    context.require_run_mutation("complete")
    calculated_hash = hashlib.sha256(canonical_report_text.encode("utf-8")).hexdigest()
    if calculated_hash != report_sha256:
        raise ResultIntegrityError(
            f"Digest mismatch: report_sha256={report_sha256!r}, calculated={calculated_hash!r}"
        )

    return insert_with_public_id_retry(
        session,
        lambda: ReconciliationResult(
            public_id=generate_public_id(PREFIX_RESULT),
            organisation_id=context.organisation_id,
            run_id=run_id,
            summary_json=summary_json,
            presentation_json=presentation_json,
            canonical_report_text=canonical_report_text,
            audit_root=audit_root,
            report_sha256=report_sha256,
        ),
        expected_constraint="reconciliation_results_public_id_key",
    )


def get_result_by_run_id(
    session: Session, context: TenantContext, run_id: int
) -> ReconciliationResult | None:
    """Retrieve reconciliation result for a specific run within the tenant scope."""
    return session.scalar(
        scoped_select(ReconciliationResult, context).where(ReconciliationResult.run_id == run_id)
    )

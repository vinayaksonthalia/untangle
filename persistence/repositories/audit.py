"""Audit event repository.

Append-only ledger of security and operational events.
Application code exposes no update or delete operations; PostgreSQL triggers
further enforce immutability at the database engine level.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_AUDIT_EVENT, generate_public_id
from persistence.models import AuditEvent
from persistence.repositories.base import scoped_select
from persistence.uow import insert_with_public_id_retry


def append_audit_event(
    session: Session,
    context: TenantContext,
    *,
    event_type: str,
    subject_type: str,
    subject_public_id: str,
    metadata_json: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Append a new immutable audit event.

    Never place raw financial statements, account numbers, credentials, or PII into metadata.
    """
    action = {
        "run.initiated": "create",
        "run.completed": "complete",
        "run.failed": "fail",
        "certificate.issued": "complete",
        "organisation.deactivated": "delete",
        "membership.assigned": "delete",
    }.get(event_type)
    if action is None:
        raise ValueError(f"unsupported audit event type {event_type!r}")
    context.require_run_mutation(action)
    req_id = request_id if request_id is not None else context.request_id
    return insert_with_public_id_retry(
        session,
        lambda: AuditEvent(
            public_id=generate_public_id(PREFIX_AUDIT_EVENT),
            organisation_id=context.organisation_id,
            actor_principal_id=context.principal_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_public_id=subject_public_id,
            request_id=req_id if req_id else None,
            metadata_json=metadata_json or {},
        ),
        expected_constraint="audit_events_public_id_key",
    )


def list_audit_events(
    session: Session,
    context: TenantContext,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """List audit events for the current organisation, ordered by most recent first."""
    stmt = (
        scoped_select(AuditEvent, context)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt).all())

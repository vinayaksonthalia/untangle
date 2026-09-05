"""Security event and control-plane audit recording."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from persistence.ids import PREFIX_SEC_EVENT, generate_public_id
from persistence.models import ControlPlaneSecurityEvent


def record_security_event(
    session: Session,
    event_type: str,
    subject_type: str,
    subject_identifier: str,
    ip_hash: str,
    user_agent_truncated: str | None = None,
    actor_principal_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Record an immutable control-plane security event.

    Uses `fn_sec_event_record` on PostgreSQL and direct model insertion on SQLite.
    Returns the public_id of the created security event.
    """
    public_id = generate_public_id(PREFIX_SEC_EVENT)
    payload = details or {}
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        session.execute(
            text(
                """
                SELECT public.fn_sec_event_record(
                    :public_id, :event_type, :actor_principal_id,
                    :subject_type, :subject_identifier, :ip_hash,
                    :user_agent_truncated, CAST(:details_json AS jsonb)
                )
                """
            ),
            {
                "public_id": public_id,
                "event_type": event_type,
                "actor_principal_id": actor_principal_id,
                "subject_type": subject_type,
                "subject_identifier": subject_identifier[:255],
                "ip_hash": ip_hash,
                "user_agent_truncated": user_agent_truncated,
                "details_json": json.dumps(payload),
            },
        )
    else:
        event = ControlPlaneSecurityEvent(
            public_id=public_id,
            event_type=event_type,
            actor_principal_id=actor_principal_id,
            subject_type=subject_type,
            subject_identifier=subject_identifier[:255],
            ip_hash=ip_hash,
            user_agent_truncated=user_agent_truncated,
            details_json=payload,
        )
        session.add(event)

    return public_id

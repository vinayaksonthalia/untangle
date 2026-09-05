"""Tests for audit ledger invariants, RLS policies, and tenant-context restoration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from persistence.ids import (
    PREFIX_AUDIT_EVENT,
    PREFIX_MEMBERSHIP,
    PREFIX_ORGANISATION,
    PREFIX_PRINCIPAL,
    generate_public_id,
)
from persistence.models import AuditEvent, Organisation, Principal


def test_audit_event_public_id_and_subject_invariants(session: Session) -> None:
    """Verify that audit records require opaque public IDs and enforce schema constraints."""
    org = Organisation(
        public_id=generate_public_id(PREFIX_ORGANISATION),
        name="Audit Test Org",
        is_active=True,
    )
    session.add(org)
    principal = Principal(
        public_id=generate_public_id(PREFIX_PRINCIPAL),
        email=f"auditor_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Auditor",
        is_active=True,
    )
    session.add(principal)
    session.flush()

    audit = AuditEvent(
        public_id=generate_public_id(PREFIX_AUDIT_EVENT),
        organisation_id=org.id,
        actor_principal_id=principal.id,
        event_type="membership.assigned",
        subject_type="organisation_membership",
        subject_public_id=generate_public_id(PREFIX_MEMBERSHIP),
        metadata_json={"role": "operator"},
        created_at=datetime.now(UTC),
    )
    session.add(audit)
    session.commit()

    retrieved = session.get(AuditEvent, audit.id)
    assert retrieved is not None
    assert retrieved.public_id.startswith("aud_")
    assert retrieved.subject_public_id.startswith("mem_")
    assert retrieved.event_type == "membership.assigned"


def test_audit_event_rls_policy_on_postgresql(session: Session, is_postgres: bool) -> None:
    """Verify fn_owner_audit_insert_policy existence and behavior on PostgreSQL."""
    if not is_postgres:
        pytest.skip("RLS policy tests require PostgreSQL")

    # Check policy existence
    policy_sql = text("""
        SELECT policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies
        WHERE tablename = 'audit_events' AND policyname = 'fn_owner_audit_insert_policy'
    """)
    row = session.execute(policy_sql).fetchone()
    assert row is not None, "fn_owner_audit_insert_policy must exist on audit_events"
    assert "untangle_fn_owner" in row.roles

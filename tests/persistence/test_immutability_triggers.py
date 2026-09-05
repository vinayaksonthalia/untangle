"""Database trigger immutability tests for audit_events, certificates, and reconciliation_results."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.ids import (
    PREFIX_AUDIT_EVENT,
    PREFIX_CERTIFICATE,
    PREFIX_RESULT,
    PREFIX_RUN,
    generate_public_id,
)
from persistence.models import (
    AuditEvent,
    CertificateRecord,
    ReconciliationResult,
    ReconciliationRun,
)
from persistence.uow import UnitOfWork


def test_audit_events_immutable_trigger(
    is_postgres: bool,
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    if not is_postgres:
        pytest.skip("Database trigger tests require PostgreSQL")

    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        event = AuditEvent(
            public_id=generate_public_id(PREFIX_AUDIT_EVENT),
            organisation_id=org_id,
            actor_principal_id=ctx.principal_id,
            event_type="run.initiated",
            subject_type="reconciliation_run",
            subject_public_id="run_test",
            metadata_json={},
        )
        uow.session.add(event)

    # 1. Attempt raw SQL UPDATE on audit_events
    with pytest.raises(DBAPIError) as exc_info:
        with UnitOfWork(session_factory, ctx) as uow:
            uow.session.execute(
                text(
                    "UPDATE audit_events SET event_type = 'tampered' WHERE organisation_id = :org_id"
                ),
                {"org_id": org_id},
            )
    assert "P0001" in str(exc_info.value) or "immutable" in str(exc_info.value).lower()

    # 2. Attempt raw SQL DELETE on audit_events
    with pytest.raises(DBAPIError) as exc_info:
        with UnitOfWork(session_factory, ctx) as uow:
            uow.session.execute(
                text("DELETE FROM audit_events WHERE organisation_id = :org_id"),
                {"org_id": org_id},
            )
    assert "P0001" in str(exc_info.value) or "immutable" in str(exc_info.value).lower()


def test_certificates_immutable_trigger(
    is_postgres: bool,
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    if not is_postgres:
        pytest.skip("Database trigger tests require PostgreSQL")

    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        run = ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=org_id,
            created_by_principal_id=ctx.principal_id,
            status="initiated",
            started_at=datetime.now(UTC),
        )
        uow.session.add(run)
        uow.session.flush()

        cert = CertificateRecord(
            public_id=generate_public_id(PREFIX_CERTIFICATE),
            organisation_id=org_id,
            run_id=run.id,
            content_sha256="a" * 64,
            report_sha256="b" * 64,
            certificate_json={"period": "2026-06"},
        )
        uow.session.add(cert)

    # Attempt raw SQL UPDATE on certificates
    with pytest.raises(DBAPIError) as exc_info:
        with UnitOfWork(session_factory, ctx) as uow:
            uow.session.execute(
                text("UPDATE certificates SET content_sha256 = :h WHERE organisation_id = :org_id"),
                {"h": "c" * 64, "org_id": org_id},
            )
    assert "P0001" in str(exc_info.value) or "immutable" in str(exc_info.value).lower()


def test_results_immutable_trigger(
    is_postgres: bool,
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    if not is_postgres:
        pytest.skip("Database trigger tests require PostgreSQL")

    ctx, org_id = tenant_a

    with UnitOfWork(session_factory, ctx) as uow:
        run = ReconciliationRun(
            public_id=generate_public_id(PREFIX_RUN),
            organisation_id=org_id,
            created_by_principal_id=ctx.principal_id,
            status="initiated",
            started_at=datetime.now(UTC),
        )
        uow.session.add(run)
        uow.session.flush()

        result = ReconciliationResult(
            public_id=generate_public_id(PREFIX_RESULT),
            organisation_id=org_id,
            run_id=run.id,
            summary_json={"matched": 10},
            presentation_json={"items": []},
            canonical_report_text="{}",
            audit_root="a" * 64,
            report_sha256="b" * 64,
        )
        uow.session.add(result)

    # Attempt raw SQL UPDATE on reconciliation_results
    with pytest.raises(DBAPIError) as exc_info:
        with UnitOfWork(session_factory, ctx) as uow:
            uow.session.execute(
                text(
                    "UPDATE reconciliation_results SET audit_root = :h WHERE organisation_id = :org_id"
                ),
                {"h": "d" * 64, "org_id": org_id},
            )
    assert "P0001" in str(exc_info.value) or "immutable" in str(exc_info.value).lower()

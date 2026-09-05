"""Period close certificate repository.

Stores and queries period close certificates bound to reconciliation runs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_CERTIFICATE, generate_public_id
from persistence.models import CertificateRecord
from persistence.repositories.base import scoped_select
from persistence.uow import insert_with_public_id_retry


def save_certificate(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    certificate_json: dict[str, Any],
    content_sha256: str,
    report_sha256: str,
    is_signed: bool = False,
    signature: str | None = None,
    public_key_pem: str | None = None,
) -> CertificateRecord:
    """Persist an issued close certificate bound to a run."""
    return insert_with_public_id_retry(
        session,
        lambda: CertificateRecord(
            public_id=generate_public_id(PREFIX_CERTIFICATE),
            organisation_id=context.organisation_id,
            run_id=run_id,
            content_sha256=content_sha256,
            report_sha256=report_sha256,
            is_signed=is_signed,
            signature=signature,
            public_key_pem=public_key_pem,
            certificate_json=certificate_json,
        ),
        expected_constraint="certificates_public_id_key",
    )


def get_certificate_by_run_id(
    session: Session, context: TenantContext, run_id: int
) -> CertificateRecord | None:
    """Retrieve certificate for a run within the tenant scope."""
    return session.scalar(
        scoped_select(CertificateRecord, context).where(CertificateRecord.run_id == run_id)
    )


def get_certificate_by_public_id(
    session: Session, context: TenantContext, public_id: str
) -> CertificateRecord | None:
    """Retrieve certificate by public ID within the tenant scope."""
    return session.scalar(
        scoped_select(CertificateRecord, context).where(CertificateRecord.public_id == public_id)
    )

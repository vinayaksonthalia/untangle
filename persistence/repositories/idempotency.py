"""Idempotency record repository.

Provides tenant-scoped idempotency key checking, collision detection,
and replay caching for asynchronous reconciliation requests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.models import IdempotencyRecord
from persistence.repositories.base import scoped_select


class IdempotencyCollisionError(Exception):
    """Raised when an idempotency key is reused with a divergent payload."""


def compute_request_hash(
    bank_bytes: bytes,
    recon_bytes: bytes,
    ledger_bytes: bytes,
    extra_params: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic SHA-256 digest over the request body and parameters."""
    hasher = hashlib.sha256()
    hasher.update(b"BANK:")
    hasher.update(hashlib.sha256(bank_bytes).digest())
    hasher.update(b"RECON:")
    hasher.update(hashlib.sha256(recon_bytes).digest())
    hasher.update(b"LEDGER:")
    hasher.update(hashlib.sha256(ledger_bytes).digest())

    if extra_params:
        canonical_params = json.dumps(extra_params, sort_keys=True, separators=(",", ":"))
        hasher.update(b"PARAMS:")
        hasher.update(canonical_params.encode("utf-8"))

    return hasher.hexdigest()


def get_idempotency_record(
    session: Session,
    context: TenantContext,
    idempotency_key: str,
) -> IdempotencyRecord | None:
    """Retrieve an existing idempotency record for this tenant if unexpired."""
    stmt = scoped_select(IdempotencyRecord, context).where(
        IdempotencyRecord.idempotency_key == idempotency_key
    )
    rec = session.scalar(stmt)
    if rec is None:
        return None

    now = datetime.now(UTC)
    # Check expiry (handle naive/aware comparison cleanly)
    rec_exp = rec.expires_at
    if rec_exp.tzinfo is None:
        rec_exp = rec_exp.replace(tzinfo=UTC)
    if rec_exp < now:
        return None

    return rec


def save_idempotency_record(
    session: Session,
    context: TenantContext,
    *,
    idempotency_key: str,
    request_hash: str,
    job_id: int,
    run_id: int,
    response_status_code: int,
    response_json: dict[str, Any],
    ttl_hours: int = 24,
) -> IdempotencyRecord:
    """Save an idempotency record for a newly accepted job."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ttl_hours)

    rec = IdempotencyRecord(
        organisation_id=context.organisation_id,
        idempotency_key=idempotency_key[:64],
        request_hash=request_hash,
        job_id=job_id,
        run_id=run_id,
        response_status_code=response_status_code,
        response_json=response_json,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(rec)
    session.flush()
    return rec

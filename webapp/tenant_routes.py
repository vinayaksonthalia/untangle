"""Tenant-isolated reconciliation API routes under /api/tenant/."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from persistence.config import (
    create_db_engine,
    create_session_factory,
    get_database_url,
)
from persistence.context import TenantContext
from persistence.repositories import (
    IdempotencyCollisionError,
    InvalidJobStateError,
    InvalidRunStateError,
    RecordNotFoundError,
    RunUnderLegalHoldError,
    get_artifact_for_run_by_type,
    get_certificate_by_run_id,
    get_job_by_public_id,
    get_result_by_run_id,
    get_run_by_id,
    get_run_by_public_id,
    list_investigations_by_run_id,
    list_runs_cursor,
    request_job_cancellation,
    set_run_legal_hold,
    soft_delete_run,
)
from persistence.service import TenantReconciliationService
from persistence.storage import ObjectNotFoundError, get_storage_backend
from webapp.agent_service import AgentEvidenceSnapshot, resolve_agent_query

router = APIRouter(prefix="/api/tenant", tags=["tenant"])

_MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MB per file


class LegalHoldPayload(BaseModel):
    legal_hold: bool = Field(
        ..., description="Whether to place (true) or release (false) legal hold"
    )


def get_tenant_context(request: Request) -> TenantContext:
    """Extract verified TenantContext from request state or fail closed."""
    ctx: TenantContext | None = getattr(request.state, "tenant_context", None)
    if not ctx:
        raise HTTPException(403, "Active organisation context is required.")
    return ctx


def get_app_session_factory() -> sessionmaker[Session]:
    """Obtain session factory for runtime tenant database interactions."""
    url = get_database_url()
    if not url:
        raise HTTPException(503, "Database is unconfigured.")
    engine = create_db_engine(url)
    return create_session_factory(engine)


async def _read_upload_bytes(upload: UploadFile | None, label: str) -> bytes:
    """Read upload into bounded byte snapshot."""
    if upload is None:
        raise HTTPException(422, f"Missing required file: {label}")
    content = await upload.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(413, f"{label} exceeds maximum allowed size of 15 MB.")
    return bytes(content)


def _parse_period_date(raw: str | None, label: str) -> date | None:
    """Parse ISO date format YYYY-MM-DD or raise 422."""
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise HTTPException(422, f"Invalid {label} date format; expected YYYY-MM-DD.") from exc


# -----------------------------------------------------------------------------
# 1. Job Submission & Ingestion
# -----------------------------------------------------------------------------


@router.post("/reconcile", status_code=202)
async def submit_tenant_reconciliation(
    request: Request,
    bank: UploadFile | None = File(None),
    bank_statement: UploadFile | None = File(None),
    recon: UploadFile | None = File(None),
    recon_report: UploadFile | None = File(None),
    ledger: UploadFile | None = File(None),
    order_ledger: UploadFile | None = File(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_period_start: str | None = Header(None, alias="X-Period-Start"),
    x_period_end: str | None = Header(None, alias="X-Period-End"),
    form_period_start: str | None = Form(None, alias="reporting_period_start"),
    form_period_end: str | None = Form(None, alias="reporting_period_end"),
) -> JSONResponse:
    """Submit reconciliation job with staged private object storage and idempotency guarantee."""
    ctx = get_tenant_context(request)

    bank_up = bank or bank_statement
    recon_up = recon or recon_report
    ledger_up = ledger or order_ledger

    bank_bytes = await _read_upload_bytes(bank_up, "bank_statement")
    recon_bytes = await _read_upload_bytes(recon_up, "recon_report")
    ledger_bytes = await _read_upload_bytes(ledger_up, "order_ledger")

    raw_start = x_period_start or form_period_start
    raw_end = x_period_end or form_period_end
    p_start = _parse_period_date(raw_start, "reporting_period_start")
    p_end = _parse_period_date(raw_end, "reporting_period_end")

    if p_start and p_end and p_start > p_end:
        raise HTTPException(
            422, "reporting_period_start must be earlier than or equal to reporting_period_end."
        )

    session_factory = get_app_session_factory()
    service = TenantReconciliationService(session_factory)

    try:
        response_json, status_code, is_replay = service.submit_reconciliation_job(
            context=ctx,
            bank_bytes=bank_bytes,
            recon_bytes=recon_bytes,
            ledger_bytes=ledger_bytes,
            bank_filename=(bank_up.filename if bank_up else None) or "bank_statement.csv",
            recon_filename=(recon_up.filename if recon_up else None) or "recon_report.json",
            ledger_filename=(ledger_up.filename if ledger_up else None) or "order_ledger.csv",
            idempotency_key=idempotency_key,
            reporting_period_start=p_start,
            reporting_period_end=p_end,
        )
    except IdempotencyCollisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, "Failed to submit reconciliation job.") from exc

    headers: dict[str, str] = {}
    if is_replay:
        headers["Idempotent-Replay"] = "true"

    return JSONResponse(content=response_json, status_code=status_code, headers=headers)


# -----------------------------------------------------------------------------
# 2. Jobs Lifecycle & Cancellation
# -----------------------------------------------------------------------------


@router.get("/jobs/{id}")
def get_job_status(id: str, request: Request) -> JSONResponse:
    """Retrieve current execution stage, heartbeat liveness, and status of a job."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        job = get_job_by_public_id(session, ctx, id)
        if job is None:
            raise HTTPException(404, f"Job {id} not found.")

        run = get_run_by_id(session, ctx, job.run_id)
        run_public_id = run.public_id if run else None

        return JSONResponse(
            {
                "id": job.public_id,
                "run_id": run_public_id,
                "status": job.status,
                "stage": job.stage,
                "attempt_count": job.attempt_count,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
                "is_cancelled": job.is_cancelled,
                "error_code": job.error_code,
                "error_summary": job.error_summary,
                "links": {
                    "status": f"/api/tenant/jobs/{job.public_id}",
                    "cancel": f"/api/tenant/jobs/{job.public_id}/cancel",
                    "run": f"/api/tenant/runs/{run_public_id}" if run_public_id else None,
                },
            }
        )


@router.post("/jobs/{id}/cancel")
def cancel_job(id: str, request: Request) -> JSONResponse:
    """Request cooperative cancellation of a queued or running job."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    try:
        with session_factory() as session:
            job = request_job_cancellation(session, ctx, id)
            if job is None:
                raise HTTPException(404, f"Job {id} not found.")
            session.commit()
            return JSONResponse(
                {
                    "job_id": job.public_id,
                    "cancelled": True,
                    "status": job.status,
                    "stage": job.stage,
                }
            )
    except RecordNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except InvalidJobStateError as exc:
        raise HTTPException(409, str(exc)) from exc


# -----------------------------------------------------------------------------
# 3. Runs (Cursor-Paginated Listing & Run Detail)
# -----------------------------------------------------------------------------


@router.get("/runs")
def list_tenant_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> JSONResponse:
    """List runs using deterministic cursor pagination (created_at DESC, id DESC)."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    try:
        with session_factory() as session:
            runs, next_cursor = list_runs_cursor(session, ctx, limit=limit, cursor=cursor)
            items = [
                {
                    "id": r.public_id,
                    "status": r.status,
                    "reporting_period_start": r.reporting_period_start.isoformat()
                    if r.reporting_period_start
                    else None,
                    "reporting_period_end": r.reporting_period_end.isoformat()
                    if r.reporting_period_end
                    else None,
                    "legal_hold": r.legal_hold,
                    "reconciliation_hash": r.reconciliation_hash,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "failed_at": r.failed_at.isoformat() if r.failed_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in runs
            ]
            return JSONResponse({"items": items, "next_cursor": next_cursor})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/runs/{id}")
def get_run_detail(id: str, request: Request) -> JSONResponse:
    """Retrieve detailed execution metadata for a run."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        run = get_run_by_public_id(session, ctx, id)
        if run is None or run.is_deleted:
            raise HTTPException(404, f"Run {id} not found.")

        return JSONResponse(
            {
                "id": run.public_id,
                "status": run.status,
                "reporting_period_start": run.reporting_period_start.isoformat()
                if run.reporting_period_start
                else None,
                "reporting_period_end": run.reporting_period_end.isoformat()
                if run.reporting_period_end
                else None,
                "legal_hold": run.legal_hold,
                "reconciliation_hash": run.reconciliation_hash,
                "bank_statement_hash": run.bank_statement_hash,
                "recon_report_hash": run.recon_report_hash,
                "order_ledger_hash": run.order_ledger_hash,
                "evidence_pack_id": run.evidence_pack_id,
                "evidence_pack_version": run.evidence_pack_version,
                "engine_version": run.engine_version,
                "schema_version": run.schema_version,
                "rule_pack_id": run.rule_pack_id,
                "rule_pack_version": run.rule_pack_version,
                "bank_adapter_id": run.bank_adapter_id,
                "bank_adapter_version": run.bank_adapter_version,
                "error_code": run.error_code,
                "error_summary": run.error_summary,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "failed_at": run.failed_at.isoformat() if run.failed_at else None,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
        )


# -----------------------------------------------------------------------------
# 4. Result Projections & Certificates
# -----------------------------------------------------------------------------


@router.get("/runs/{id}/presentation")
def get_run_presentation(id: str, request: Request) -> JSONResponse:
    """Retrieve structured presentation view model of a completed run."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        run = get_run_by_public_id(session, ctx, id)
        if run is None or run.is_deleted:
            raise HTTPException(404, f"Run {id} not found.")
        if run.status != "completed":
            raise HTTPException(404, f"Run {id} is not completed (status: {run.status}).")

        result = get_result_by_run_id(session, ctx, run.id)
        if result is None or not result.presentation_json:
            raise HTTPException(404, f"Presentation payload for run {id} not found.")

        return JSONResponse(result.presentation_json)


@router.get("/runs/{id}/investigations")
def get_run_investigations(id: str, request: Request) -> JSONResponse:
    """Retrieve root-cause investigations cases and summary for a completed run."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        run = get_run_by_public_id(session, ctx, id)
        if run is None or run.is_deleted:
            raise HTTPException(404, f"Run {id} not found.")
        if run.status != "completed":
            raise HTTPException(404, f"Run {id} is not completed (status: {run.status}).")

        records = list_investigations_by_run_id(session, ctx, run.id)
        cases: list[dict[str, Any]] = []
        resolved_count = 0

        for rec in records:
            if rec.resolved:
                resolved_count += 1
            cases.append(
                rec.details_json
                or {
                    "line_key": rec.line_key,
                    "root_cause": rec.root_cause,
                    "resolved": rec.resolved,
                    "confidence": rec.confidence,
                    "variance_paise": rec.variance_paise,
                }
            )

        total = len(cases)
        return JSONResponse(
            {
                "run_id": run.public_id,
                "summary": {
                    "total": total,
                    "resolved": resolved_count,
                    "abstained": total - resolved_count,
                },
                "cases": cases,
            }
        )


@router.get("/runs/{id}/certificate")
def get_run_certificate(id: str, request: Request) -> JSONResponse:
    """Retrieve the authoritative period close certificate for a completed run."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        run = get_run_by_public_id(session, ctx, id)
        if run is None or run.is_deleted:
            raise HTTPException(404, f"Run {id} not found.")
        if run.status != "completed":
            raise HTTPException(404, f"Run {id} is not completed (status: {run.status}).")

        cert = get_certificate_by_run_id(session, ctx, run.id)
        if cert is None:
            raise HTTPException(404, f"Certificate for run {id} not found.")

        payload = {
            "certificate": cert.certificate_json,
            "content_sha256": cert.content_sha256,
            "report_sha256": cert.report_sha256,
            "signed": cert.is_signed,
            "signature": cert.signature,
            "public_key_pem": cert.public_key_pem,
        }
        return JSONResponse(payload)


# -----------------------------------------------------------------------------
# 5. Output Artifact Downloads
# -----------------------------------------------------------------------------


@router.get("/runs/{id}/artifacts/{artifact_type}")
def download_run_artifact(id: str, artifact_type: str, request: Request) -> Response:
    """Download output artifacts (e.g. tally_xml, report_json) from private tenant storage."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        run = get_run_by_public_id(session, ctx, id)
        if run is None or run.is_deleted:
            raise HTTPException(404, f"Run {id} not found.")
        if run.status != "completed":
            raise HTTPException(404, f"Run {id} is not completed (status: {run.status}).")

        artifact = get_artifact_for_run_by_type(session, ctx, run.id, artifact_type)
        if artifact is None:
            raise HTTPException(404, f"Artifact '{artifact_type}' for run {id} not found.")

        storage = get_storage_backend()
        try:
            data = storage.retrieve_bytes(artifact.object_key)
        except ObjectNotFoundError as exc:
            raise HTTPException(
                404, f"Artifact object not found in storage: {artifact.object_key}"
            ) from exc

        headers = {
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Cache-Control": "private, no-cache",
        }
        if artifact.etag:
            headers["ETag"] = artifact.etag

        return Response(
            content=data,
            media_type=artifact.media_type,
            headers=headers,
        )


# -----------------------------------------------------------------------------
# 6. Legal Hold & Deletion Safeguards
# -----------------------------------------------------------------------------


@router.post("/runs/{id}/legal-hold")
def set_legal_hold_status(id: str, payload: LegalHoldPayload, request: Request) -> JSONResponse:
    """Place or release a legal hold on a reconciliation run."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    try:
        with session_factory() as session:
            run = set_run_legal_hold(session, ctx, id, payload.legal_hold)
            session.commit()
            return JSONResponse({"id": run.public_id, "legal_hold": run.legal_hold})
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except RecordNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/runs/{id}")
def delete_tenant_run(id: str, request: Request) -> JSONResponse:
    """Soft-delete a reconciliation run; blocked with 409 if legal hold is active."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    try:
        with session_factory() as session:
            success = soft_delete_run(session, ctx, id)
            if not success:
                raise HTTPException(404, f"Run {id} not found.")
            session.commit()
            return JSONResponse({"id": id, "deleted": True})
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except RunUnderLegalHoldError as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(409, str(exc)) from exc


# -----------------------------------------------------------------------------
# 7. Non-Overlapping Multi-Month Comparison
# -----------------------------------------------------------------------------


class RunComparisonRequest(BaseModel):
    base_run_id: str = Field(..., description="Public ID of base reconciliation run")
    target_run_id: str = Field(..., description="Public ID of target reconciliation run")


@router.post("/runs/compare")
def compare_tenant_runs(payload: RunComparisonRequest, request: Request) -> JSONResponse:
    """Compare two completed non-overlapping reconciliation runs."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()
    service = TenantReconciliationService(session_factory)

    try:
        result = service.compare_runs(ctx, payload.base_run_id, payload.target_run_id)
        return JSONResponse(result)
    except RecordNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidRunStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# -----------------------------------------------------------------------------
# 8. Advisory Untany Agent Evidence Queries
# -----------------------------------------------------------------------------


class AgentQueryRequest(BaseModel):
    run_id: str = Field(..., description="Public ID of reconciliation run")
    query: str = Field(
        ..., min_length=1, max_length=1000, description="Advisory inquiry about the run"
    )


@router.post("/agent/query")
def query_agent_evidence(payload: AgentQueryRequest, request: Request) -> JSONResponse:
    """Advisory tenant query resolution over authoritative run evidence."""
    ctx = get_tenant_context(request)
    session_factory = get_app_session_factory()

    with session_factory() as session:
        snapshot = AgentEvidenceSnapshot.load(session, ctx, payload.run_id)
        if snapshot is None:
            raise HTTPException(404, f"Run {payload.run_id} not found.")

        result = resolve_agent_query(snapshot, payload.query)
        return JSONResponse(result)

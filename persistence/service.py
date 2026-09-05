"""Tenant reconciliation service coordinating the three-phase transaction lifecycle.

Decouples long-running deterministic reconciliation from open database transactions,
ensures atomic persistence of completion artifacts, and guarantees safe failure transitions.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from engine.certificate import _canonical, certificate_note, issue_certificate
from engine.version import ENGINE_VERSION
from persistence.context import TenantContext
from persistence.repositories.artifact import (
    save_artifact_metadata,
    save_uploaded_file_metadata,
)
from persistence.repositories.audit import append_audit_event
from persistence.repositories.base import RecordNotFoundError
from persistence.repositories.certificate import get_certificate_by_run_id, save_certificate
from persistence.repositories.control_plane import get_organisation
from persistence.repositories.idempotency import (
    IdempotencyCollisionError,
    compute_request_hash,
    get_idempotency_record,
    save_idempotency_record,
)
from persistence.repositories.investigation import (
    list_investigations_by_run_id,
    save_investigations,
)
from persistence.repositories.job import create_reconciliation_job
from persistence.repositories.result import get_result_by_run_id, save_result
from persistence.repositories.run import (
    InvalidRunStateError,
    complete_run,
    create_run,
    fail_run,
    get_run_by_public_id,
    lock_run_for_update,
)
from persistence.storage import (
    ObjectStorageBackend,
    generate_input_object_key,
    get_storage_backend,
)
from persistence.uow import UnitOfWork


class ReconciliationServiceError(Exception):
    """Base exception for reconciliation service failures."""


class TenantReconciliationService:
    """Service orchestrating tenant runs across the persistence and deterministic engine boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: ObjectStorageBackend | None = None,
    ) -> None:
        self.session_factory = session_factory
        self._storage = storage

    @property
    def storage(self) -> ObjectStorageBackend:
        if self._storage is None:
            self._storage = get_storage_backend()
        return self._storage

    def execute_reconciliation(
        self,
        context: TenantContext,
        bank_bytes: bytes,
        recon_bytes: bytes,
        ledger_bytes: bytes,
        *,
        bank_filename: str = "bank_statement.csv",
        recon_filename: str = "recon_report.json",
        ledger_filename: str = "order_ledger.csv",
    ) -> dict[str, Any]:
        """Execute a full tenant reconciliation under the three-phase transaction lifecycle.

        Phase 1 (DB Transaction): Record initiated run and file metadata.
        Phase 2 (In-Memory Engine): Execute deterministic reconciliation with zero DB locks held.
        Phase 3 (DB Transaction): Atomically persist results, certificate, investigations, and audit event.
        Failure Handling: If Phase 2 or 3 fails, record run failure with a sanitized error code in a clean transaction.
        """
        bank_hash = hashlib.sha256(bank_bytes).hexdigest()
        recon_hash = hashlib.sha256(recon_bytes).hexdigest()
        ledger_hash = hashlib.sha256(ledger_bytes).hexdigest()

        # -------------------------------------------------------------------
        # Phase 1: Ingestion & Run Initiation (Transaction 1)
        # -------------------------------------------------------------------
        with UnitOfWork(self.session_factory, context) as uow:
            assert uow.session is not None
            run = create_run(uow.session, context)
            run_id = run.id
            run_public_id = run.public_id

            save_uploaded_file_metadata(
                uow.session,
                context,
                run_id,
                file_role="bank_statement",
                original_filename=bank_filename,
                content_type="text/csv",
                size_bytes=len(bank_bytes),
                sha256_checksum=bank_hash,
            )
            save_uploaded_file_metadata(
                uow.session,
                context,
                run_id,
                file_role="recon_report",
                original_filename=recon_filename,
                content_type="application/json",
                size_bytes=len(recon_bytes),
                sha256_checksum=recon_hash,
            )
            save_uploaded_file_metadata(
                uow.session,
                context,
                run_id,
                file_role="order_ledger",
                original_filename=ledger_filename,
                content_type="text/csv",
                size_bytes=len(ledger_bytes),
                sha256_checksum=ledger_hash,
            )

            append_audit_event(
                uow.session,
                context,
                event_type="run.initiated",
                subject_type="reconciliation_run",
                subject_public_id=run_public_id,
                metadata_json={"bank_hash": bank_hash, "recon_hash": recon_hash},
            )

        # -------------------------------------------------------------------
        # Phase 2: Engine Execution (Zero DB connections or locks held)
        # -------------------------------------------------------------------
        try:
            from engine.journal import journal_json_to_tally_xml
            from engine.service import reconcile_bytes
            from webapp.presentation import build_presentation_payload

            # Deterministic, pure in-memory execution
            report = reconcile_bytes(bank_bytes, recon_bytes, ledger_bytes)
            cert_envelope = issue_certificate(report)
            presentation = build_presentation_payload(report, certificate=cert_envelope)
            tally_xml = journal_json_to_tally_xml(
                report.get("journal") or [], company="Your Company Name"
            )

            # Canonical byte serialization and digest
            canonical_bytes = _canonical(report)
            canonical_text = canonical_bytes.decode("utf-8")
            report_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
            content_sha256 = cert_envelope["content_sha256"]

        except Exception as exc:
            # Handle failure during Phase 2
            try:
                self._record_failure(
                    context,
                    run_id,
                    run_public_id,
                    error_code="RECONCILIATION_FAILED",
                    error_summary=(
                        "The deterministic reconciliation engine could not process the input."
                    ),
                )
            except ReconciliationServiceError as record_error:
                exc.add_note(str(record_error))
            raise

        # -------------------------------------------------------------------
        # Phase 3: Atomic Completion & Persistence (Transaction 2)
        # -------------------------------------------------------------------
        try:
            with UnitOfWork(self.session_factory, context) as uow:
                assert uow.session is not None

                # Lock before inserting any one-to-one completion records. If a caller
                # retries after an uncertain commit, return the already committed result
                # instead of colliding with immutable unique rows.
                locked_run = lock_run_for_update(uow.session, context, run_id)
                if locked_run is None:
                    raise InvalidRunStateError("The reconciliation run no longer exists.")
                if locked_run.status == "completed":
                    if locked_run.reconciliation_hash != report_sha256:
                        raise InvalidRunStateError(
                            "A completed run cannot be replaced by different output."
                        )
                    # Idempotent retry: return the certificate persisted at first completion,
                    # never a freshly re-issued one (ECDSA re-signing would change the
                    # signature for identical inputs).
                    return self._authoritative_completed_result(
                        uow.session, context, run_id, run_public_id, report, report_sha256
                    )
                if locked_run.status in ("failed", "aborted"):
                    # A concurrent worker already recorded this run as terminal. Do not
                    # complete it, and do NOT fall through to failure recording — that would
                    # overwrite the original failure diagnostics and append a duplicate
                    # immutable run.failed audit event.
                    raise InvalidRunStateError(
                        f"Run {run_public_id} is already {locked_run.status}; refusing to complete "
                        "or overwrite a terminal run."
                    )

                # Persist canonical results
                save_result(
                    uow.session,
                    context,
                    run_id,
                    summary_json=report.get("totals") or {},
                    presentation_json=presentation,
                    canonical_report_text=canonical_text,
                    audit_root=report.get("audit_root", ""),
                    report_sha256=report_sha256,
                )

                # Persist investigations
                raw_investigations = report.get("investigations") or []
                save_investigations(uow.session, context, run_id, raw_investigations)

                # Persist certificate
                save_certificate(
                    uow.session,
                    context,
                    run_id,
                    certificate_json=cert_envelope["certificate"],
                    content_sha256=content_sha256,
                    report_sha256=report_sha256,
                    is_signed=cert_envelope.get("signed", False),
                    signature=cert_envelope.get("signature"),
                    public_key_pem=cert_envelope.get("public_key_pem"),
                )

                # Persist artifact metadata
                save_artifact_metadata(
                    uow.session,
                    context,
                    run_id,
                    artifact_type="tally_xml",
                    filename="untangle_tally_vouchers.xml",
                    media_type="application/xml",
                    size_bytes=len(tally_xml.encode("utf-8")),
                    content_sha256=hashlib.sha256(tally_xml.encode("utf-8")).hexdigest(),
                )
                save_artifact_metadata(
                    uow.session,
                    context,
                    run_id,
                    artifact_type="report_json",
                    filename="untangle_report.json",
                    media_type="application/json",
                    size_bytes=len(canonical_bytes),
                    content_sha256=report_sha256,
                )

                # Append audit event
                append_audit_event(
                    uow.session,
                    context,
                    event_type="run.completed",
                    subject_type="reconciliation_run",
                    subject_public_id=run_public_id,
                    metadata_json={
                        "report_sha256": report_sha256,
                        "content_sha256": content_sha256,
                    },
                )

                # Complete run record
                complete_run(
                    uow.session,
                    context,
                    run_id,
                    reconciliation_hash=report_sha256,
                    bank_statement_hash=bank_hash,
                    recon_report_hash=recon_hash,
                    order_ledger_hash=ledger_hash,
                    evidence_pack_id=(report.get("config", {}).get("evidence_pack") or {}).get(
                        "pack_id"
                    ),
                    evidence_pack_version=(report.get("config", {}).get("evidence_pack") or {}).get(
                        "version"
                    ),
                )

        except InvalidRunStateError:
            # Expected lifecycle conflict: the run is missing, already terminal, or a
            # completed run diverged. This attempt persisted nothing, so never rewrite the
            # run's failure state or append a duplicate audit event — just surface it.
            raise
        except Exception as exc:
            # Handle unexpected failure during Phase 3
            try:
                self._record_failure(
                    context,
                    run_id,
                    run_public_id,
                    error_code="PERSISTENCE_FAILURE",
                    error_summary="The reconciliation output could not be persisted.",
                )
            except ReconciliationServiceError as record_error:
                exc.add_note(str(record_error))
            raise

        return {
            "run_public_id": run_public_id,
            "report": report,
            "certificate": cert_envelope,
            "presentation": presentation,
            "report_sha256": report_sha256,
        }

    def _authoritative_completed_result(
        self,
        session: Session,
        context: TenantContext,
        run_id: int,
        run_public_id: str,
        report: dict[str, Any],
        report_sha256: str,
    ) -> dict[str, Any]:
        """Return the result of an already-completed run for an idempotent retry.

        Reads the certificate stored at first completion instead of recomputing it, so a
        retry with identical inputs returns the authoritative (identical) envelope rather
        than a freshly re-signed one. The deterministic report is recomputed identically.
        """
        from webapp.presentation import build_presentation_payload

        stored = get_certificate_by_run_id(session, context, run_id)
        if stored is None:
            raise InvalidRunStateError(
                "The completed run is missing its persisted certificate; refusing to fabricate one."
            )
        cert_envelope: dict[str, Any] = {
            "certificate": stored.certificate_json,
            "content_sha256": stored.content_sha256,
            "signed": stored.is_signed,
            # Reproduce the authoritative trust guidance issue_certificate emits. It is a pure
            # function of the signed state, so this reconstructs the identical envelope without
            # re-issuing (and re-signing) the certificate.
            "note": certificate_note(signed=stored.is_signed),
        }
        if stored.signature is not None:
            cert_envelope["signature"] = stored.signature
        if stored.public_key_pem is not None:
            cert_envelope["public_key_pem"] = stored.public_key_pem
        presentation = build_presentation_payload(report, certificate=cert_envelope)
        return {
            "run_public_id": run_public_id,
            "report": report,
            "certificate": cert_envelope,
            "presentation": presentation,
            "report_sha256": report_sha256,
        }

    def _record_failure(
        self,
        context: TenantContext,
        run_id: int,
        run_public_id: str,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        """Record run failure in a separate clean transaction."""
        try:
            with UnitOfWork(self.session_factory, context) as uow:
                assert uow.session is not None
                run = fail_run(
                    uow.session,
                    context,
                    run_id,
                    error_code=error_code,
                    error_summary=error_summary,
                )
                if run.status == "completed":
                    return
                append_audit_event(
                    uow.session,
                    context,
                    event_type="run.failed",
                    subject_type="reconciliation_run",
                    subject_public_id=run_public_id,
                    metadata_json={"error_code": error_code},
                )
        except Exception as exc:
            raise ReconciliationServiceError(
                "The original operation failed and its failure state could not be recorded."
            ) from exc

    def submit_reconciliation_job(
        self,
        context: TenantContext,
        bank_bytes: bytes,
        recon_bytes: bytes,
        ledger_bytes: bytes,
        *,
        bank_filename: str = "bank_statement.csv",
        recon_filename: str = "recon_report.json",
        ledger_filename: str = "order_ledger.csv",
        idempotency_key: str | None = None,
        reporting_period_start: date | None = None,
        reporting_period_end: date | None = None,
        engine_version: str | None = None,
        schema_version: str | None = "1.0.0",
        rule_pack_id: str | None = None,
        rule_pack_version: str | None = None,
        bank_adapter_id: str | None = None,
        bank_adapter_version: str | None = None,
    ) -> tuple[dict[str, Any], int, bool]:
        """Submit a background reconciliation job with durable storage and idempotency.

        Returns (response_json, http_status_code, is_idempotent_replay).
        """
        if engine_version is None:
            engine_version = ENGINE_VERSION
        if (
            reporting_period_start is not None
            and reporting_period_end is not None
            and reporting_period_start > reporting_period_end
        ):
            raise ValueError(
                f"reporting_period_start ({reporting_period_start}) cannot be after reporting_period_end ({reporting_period_end})"
            )

        extra_params = {
            "period_start": reporting_period_start.isoformat() if reporting_period_start else None,
            "period_end": reporting_period_end.isoformat() if reporting_period_end else None,
            "rule_pack_id": rule_pack_id,
            "bank_adapter_id": bank_adapter_id,
        }
        request_hash = compute_request_hash(bank_bytes, recon_bytes, ledger_bytes, extra_params)

        # 1. Check idempotency record before taking any action
        if idempotency_key:
            with UnitOfWork(self.session_factory, context) as uow:
                assert uow.session is not None
                existing = get_idempotency_record(uow.session, context, idempotency_key)
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise IdempotencyCollisionError(
                            "Idempotency key reused with conflicting request payload or parameters"
                        )
                    return existing.response_json, existing.response_status_code, True

        bank_hash = hashlib.sha256(bank_bytes).hexdigest()
        recon_hash = hashlib.sha256(recon_bytes).hexdigest()
        ledger_hash = hashlib.sha256(ledger_bytes).hexdigest()

        # 2. Upload input files to durable storage
        with UnitOfWork(self.session_factory, context) as uow:
            assert uow.session is not None
            org = get_organisation(uow.session, context.organisation_id)
            org_public_id = org.public_id if org else f"org_{context.organisation_id}"

        upload_run_token = secrets.token_hex(8)
        k_bank = generate_input_object_key(
            org_public_id, upload_run_token, "bank_statement", bank_hash, bank_filename
        )
        k_recon = generate_input_object_key(
            org_public_id, upload_run_token, "recon_report", recon_hash, recon_filename
        )
        k_ledger = generate_input_object_key(
            org_public_id, upload_run_token, "order_ledger", ledger_hash, ledger_filename
        )

        staged_keys = [k_bank, k_recon, k_ledger]
        try:
            meta_bank = self.storage.store_bytes(k_bank, bank_bytes, "text/csv")
            meta_recon = self.storage.store_bytes(k_recon, recon_bytes, "application/json")
            meta_ledger = self.storage.store_bytes(k_ledger, ledger_bytes, "text/csv")
        except Exception:
            for key in staged_keys:
                try:
                    self.storage.delete_object(key)
                except Exception:
                    pass
            raise

        # 3. Create run and job atomically in database with compensation on rollback
        try:
            with UnitOfWork(self.session_factory, context) as uow:
                assert uow.session is not None

                # Re-check idempotency under transaction
                if idempotency_key:
                    existing = get_idempotency_record(uow.session, context, idempotency_key)
                    if existing is not None:
                        if existing.request_hash != request_hash:
                            raise IdempotencyCollisionError(
                                "Idempotency key reused with conflicting request payload"
                            )
                        for k in staged_keys:
                            try:
                                self.storage.delete_object(k)
                            except Exception:
                                pass
                        return existing.response_json, existing.response_status_code, True

                run = create_run(uow.session, context)
                run.reporting_period_start = reporting_period_start
                run.reporting_period_end = reporting_period_end
                run.engine_version = engine_version
                run.schema_version = schema_version
                run.rule_pack_id = rule_pack_id
                run.rule_pack_version = rule_pack_version
                run.bank_adapter_id = bank_adapter_id
                run.bank_adapter_version = bank_adapter_version
                run.bank_statement_hash = bank_hash
                run.recon_report_hash = recon_hash
                run.order_ledger_hash = ledger_hash

                run_id = run.id
                run_public_id = run.public_id

                save_uploaded_file_metadata(
                    uow.session,
                    context,
                    run_id,
                    file_role="bank_statement",
                    original_filename=bank_filename,
                    content_type="text/csv",
                    size_bytes=len(bank_bytes),
                    sha256_checksum=bank_hash,
                    backend=meta_bank.backend,
                    object_key=meta_bank.key,
                    etag=meta_bank.etag,
                    version_id=meta_bank.version_id,
                )
                save_uploaded_file_metadata(
                    uow.session,
                    context,
                    run_id,
                    file_role="recon_report",
                    original_filename=recon_filename,
                    content_type="application/json",
                    size_bytes=len(recon_bytes),
                    sha256_checksum=recon_hash,
                    backend=meta_recon.backend,
                    object_key=meta_recon.key,
                    etag=meta_recon.etag,
                    version_id=meta_recon.version_id,
                )
                save_uploaded_file_metadata(
                    uow.session,
                    context,
                    run_id,
                    file_role="order_ledger",
                    original_filename=ledger_filename,
                    content_type="text/csv",
                    size_bytes=len(ledger_bytes),
                    sha256_checksum=ledger_hash,
                    backend=meta_ledger.backend,
                    object_key=meta_ledger.key,
                    etag=meta_ledger.etag,
                    version_id=meta_ledger.version_id,
                )

                append_audit_event(
                    uow.session,
                    context,
                    event_type="run.initiated",
                    subject_type="reconciliation_run",
                    subject_public_id=run_public_id,
                    metadata_json={
                        "bank_hash": bank_hash,
                        "recon_hash": recon_hash,
                        "ledger_hash": ledger_hash,
                    },
                )

                job = create_reconciliation_job(uow.session, context, run_id)
                job_public_id = job.public_id

                response_json = {
                    "job_id": job_public_id,
                    "run_id": run_public_id,
                    "status": "queued",
                    "stage": "queued",
                    "created_at": job.created_at.isoformat(),
                    "links": {
                        "status": f"/api/tenant/jobs/{job_public_id}",
                        "cancel": f"/api/tenant/jobs/{job_public_id}/cancel",
                        "run": f"/api/tenant/runs/{run_public_id}",
                    },
                }

                if idempotency_key:
                    saved_idempotency = save_idempotency_record(
                        uow.session,
                        context,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        job_id=job.id,
                        run_id=run_id,
                        response_status_code=202,
                        response_json=response_json,
                    )
                    # A concurrent request may have won the unique-key race;
                    # its committed response is authoritative and our staged
                    # objects must not be retained.
                    if saved_idempotency.job_id != job.id:
                        for k in staged_keys:
                            try:
                                self.storage.delete_object(k)
                            except Exception:
                                pass
                        return (
                            saved_idempotency.response_json,
                            saved_idempotency.response_status_code,
                            True,
                        )

            return response_json, 202, False

        except Exception:
            for k in staged_keys:
                try:
                    self.storage.delete_object(k)
                except Exception:
                    pass
            raise

    def compare_runs(
        self,
        context: TenantContext,
        base_run_public_id: str,
        target_run_public_id: str,
    ) -> dict[str, Any]:
        """Compare two completed non-overlapping reconciliation runs within tenant scope.

        Enforces non-overlapping reporting periods, calculates integer paise deltas,
        and analyzes rail distributions and root-cause drift.
        """
        from collections import Counter

        with UnitOfWork(self.session_factory, context) as uow:
            assert uow.session is not None
            base_run = get_run_by_public_id(uow.session, context, base_run_public_id)
            if base_run is None or base_run.is_deleted:
                raise RecordNotFoundError(f"Base run {base_run_public_id!r} not found.")

            target_run = get_run_by_public_id(uow.session, context, target_run_public_id)
            if target_run is None or target_run.is_deleted:
                raise RecordNotFoundError(f"Target run {target_run_public_id!r} not found.")

            if base_run.status != "completed":
                raise InvalidRunStateError(
                    f"Base run {base_run.public_id} is not completed (status: {base_run.status})."
                )
            if target_run.status != "completed":
                raise InvalidRunStateError(
                    f"Target run {target_run.public_id} is not completed (status: {target_run.status})."
                )

            if not base_run.reporting_period_start or not base_run.reporting_period_end:
                raise ValueError(
                    f"Base run {base_run.public_id} does not have configured reporting periods."
                )
            if not target_run.reporting_period_start or not target_run.reporting_period_end:
                raise ValueError(
                    f"Target run {target_run.public_id} does not have configured reporting periods."
                )

            # Enforce non-overlapping periods
            is_non_overlapping = (
                base_run.reporting_period_end < target_run.reporting_period_start
                or target_run.reporting_period_end < base_run.reporting_period_start
            )
            if not is_non_overlapping:
                raise ValueError(
                    f"Comparison requires non-overlapping reporting periods; "
                    f"base [{base_run.reporting_period_start} to {base_run.reporting_period_end}] "
                    f"overlaps target [{target_run.reporting_period_start} to {target_run.reporting_period_end}]."
                )

            base_res = get_result_by_run_id(uow.session, context, base_run.id)
            target_res = get_result_by_run_id(uow.session, context, target_run.id)

            base_pres = (base_res.presentation_json if base_res else {}) or {}
            target_pres = (target_res.presentation_json if target_res else {}) or {}

            base_summary = base_pres.get("summary") or {}
            target_summary = target_pres.get("summary") or {}

            # Exact integer paise deltas
            deltas = {
                "total_credit_delta_paise": target_summary.get("total_credit_paise", 0)
                - base_summary.get("total_credit_paise", 0),
                "reconciled_delta_paise": target_summary.get("reconciled_paise", 0)
                - base_summary.get("reconciled_paise", 0),
                "unresolved_delta_paise": target_summary.get("unresolved_paise", 0)
                - base_summary.get("unresolved_paise", 0),
                "fee_gst_recoverable_delta_paise": target_summary.get(
                    "fee_gst_recoverable_paise", 0
                )
                - base_summary.get("fee_gst_recoverable_paise", 0),
                "exception_count_delta": target_summary.get("exception_count", 0)
                - base_summary.get("exception_count", 0),
            }

            # Rails comparison
            base_rails = {
                r.get("rail"): r for r in base_pres.get("rails") or [] if isinstance(r, dict)
            }
            target_rails = {
                r.get("rail"): r for r in target_pres.get("rails") or [] if isinstance(r, dict)
            }
            all_rails = sorted(
                set(base_rails.keys()) | set(target_rails.keys()), key=lambda x: str(x)
            )

            rails_comp = []
            for r_key in all_rails:
                b_r = base_rails.get(r_key) or {}
                t_r = target_rails.get(r_key) or {}
                b_amt = b_r.get("amount_paise") or 0
                t_amt = t_r.get("amount_paise") or 0
                rails_comp.append(
                    {
                        "rail": r_key,
                        "label": t_r.get("label") or b_r.get("label") or r_key,
                        "base_amount_paise": b_amt,
                        "target_amount_paise": t_amt,
                        "delta_amount_paise": t_amt - b_amt,
                        "base_count": b_r.get("count") or 0,
                        "target_count": t_r.get("count") or 0,
                        "delta_count": (t_r.get("count") or 0) - (b_r.get("count") or 0),
                    }
                )

            # Root-cause drift
            base_invs = list_investigations_by_run_id(uow.session, context, base_run.id)
            target_invs = list_investigations_by_run_id(uow.session, context, target_run.id)

            base_counts = Counter(inv.root_cause for inv in base_invs)
            target_counts = Counter(inv.root_cause for inv in target_invs)
            all_rcs = sorted(set(base_counts.keys()) | set(target_counts.keys()))

            root_cause_drift = []
            for rc in all_rcs:
                b_c = base_counts.get(rc, 0)
                t_c = target_counts.get(rc, 0)
                root_cause_drift.append(
                    {
                        "root_cause": rc,
                        "base_count": b_c,
                        "target_count": t_c,
                        "delta_count": t_c - b_c,
                    }
                )

            return {
                "base_run": {
                    "id": base_run.public_id,
                    "reporting_period_start": base_run.reporting_period_start.isoformat(),
                    "reporting_period_end": base_run.reporting_period_end.isoformat(),
                    "summary": base_summary,
                },
                "target_run": {
                    "id": target_run.public_id,
                    "reporting_period_start": target_run.reporting_period_start.isoformat(),
                    "reporting_period_end": target_run.reporting_period_end.isoformat(),
                    "summary": target_summary,
                },
                "period_relationship": (
                    "subsequent"
                    if base_run.reporting_period_end < target_run.reporting_period_start
                    else "preceding"
                ),
                "deltas": deltas,
                "rails_comparison": rails_comp,
                "root_cause_drift": root_cause_drift,
            }

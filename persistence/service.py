"""Tenant reconciliation service coordinating the three-phase transaction lifecycle.

Decouples long-running deterministic reconciliation from open database transactions,
ensures atomic persistence of completion artifacts, and guarantees safe failure transitions.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from engine.certificate import _canonical, issue_certificate
from persistence.context import TenantContext
from persistence.repositories.artifact import (
    save_artifact_metadata,
    save_uploaded_file_metadata,
)
from persistence.repositories.audit import append_audit_event
from persistence.repositories.certificate import get_certificate_by_run_id, save_certificate
from persistence.repositories.investigation import save_investigations
from persistence.repositories.result import save_result
from persistence.repositories.run import (
    InvalidRunStateError,
    complete_run,
    create_run,
    fail_run,
    lock_run_for_update,
)
from persistence.uow import UnitOfWork


class ReconciliationServiceError(Exception):
    """Base exception for reconciliation service failures."""


class TenantReconciliationService:
    """Service orchestrating tenant runs across the persistence and deterministic engine boundaries."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

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
                "The completed run is missing its persisted certificate; refusing to "
                "fabricate one."
            )
        cert_envelope: dict[str, Any] = {
            "certificate": stored.certificate_json,
            "content_sha256": stored.content_sha256,
            "signed": stored.is_signed,
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

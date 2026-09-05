"""Durable asynchronous worker service for reconciliation jobs.

Processes queued reconciliation jobs with atomic claiming, lease heartbeats,
cooperative cancellation, attempt fencing, deterministic engine execution,
S3 artifact promotion, and single-transaction completion under tenant isolation.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import secrets
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from engine.certificate import _canonical, issue_certificate
from engine.ingest import InputError
from engine.journal import journal_json_to_tally_xml
from engine.service import reconcile_bytes
from persistence.config import (
    create_db_engine,
    create_session_factory,
    get_database_url,
    get_worker_database_url,
)
from persistence.context import Role, TenantContext
from persistence.models import UploadedFileMetadata
from persistence.repositories.artifact import (
    list_uploaded_files_for_run,
    save_artifact_metadata,
)
from persistence.repositories.audit import append_audit_event
from persistence.repositories.certificate import save_certificate
from persistence.repositories.control_plane import get_organisation
from persistence.repositories.investigation import save_investigations
from persistence.repositories.job import (
    JobFencingError,
    cancel_ack_job,
    check_job_cancellation,
    claim_next_job,
    complete_job_fenced,
    fail_job,
    heartbeat_job,
    revalidate_job_creator,
    transition_job_stage,
)
from persistence.repositories.result import save_result
from persistence.repositories.run import (
    complete_run,
    get_run_by_id,
)
from persistence.storage import (
    ObjectStorageBackend,
    generate_artifact_object_key,
    generate_attempt_artifact_key,
    get_storage_backend,
)
from persistence.uow import UnitOfWork
from webapp.presentation import build_presentation_payload

logger = logging.getLogger("untangle.worker")


class ReconciliationWorker:
    """Worker service executing reconciliation jobs with durable leasing and fencing."""

    def __init__(
        self,
        app_session_factory: sessionmaker[Session],
        *,
        worker_session_factory: sessionmaker[Session] | None = None,
        storage: ObjectStorageBackend | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        self.app_session_factory = app_session_factory
        self.worker_session_factory = worker_session_factory or app_session_factory
        self.storage = storage or get_storage_backend()
        self.worker_id = worker_id or f"worker_{os.getpid()}_{secrets.token_hex(4)}"
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        """Attempt to claim and execute one job. Returns True if a job was processed."""
        with self.worker_session_factory() as session:
            claimed = claim_next_job(session, self.worker_id, self.lease_seconds)

        if not claimed:
            return False

        self._execute_claimed_job(claimed)
        return True

    process_next_job = run_once

    def run_loop(
        self,
        *,
        poll_interval: float = 1.0,
        stop_event: threading.Event | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Continuously poll for and process queued jobs until stopped."""
        iterations = 0
        while True:
            if stop_event and stop_event.is_set():
                break
            if max_iterations is not None and iterations >= max_iterations:
                break

            processed = False
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("Unexpected error in worker loop iteration")

            iterations += 1
            if not processed:
                time.sleep(poll_interval)

    def _execute_claimed_job(self, claimed: dict[str, Any]) -> None:
        job_id = claimed["job_id"]
        org_id = claimed["organisation_id"]
        run_id = claimed["run_id"]
        attempt_token = claimed["attempt_token"]
        lease_generation = claimed["lease_generation"]

        # Background heartbeat thread
        heartbeat_stop = threading.Event()
        heartbeat_error = threading.Event()

        def _heartbeat_runner():
            interval = max(2.0, float(self.lease_seconds) / 3.0)
            while not heartbeat_stop.wait(interval):
                try:
                    with self.worker_session_factory() as hb_session:
                        ok = heartbeat_job(
                            hb_session,
                            job_id,
                            self.worker_id,
                            attempt_token,
                            lease_generation,
                            self.lease_seconds,
                        )
                        if not ok:
                            heartbeat_error.set()
                            logger.warning(
                                f"Heartbeat lost for job {job_id} generation {lease_generation}"
                            )
                            break
                except Exception:
                    heartbeat_error.set()
                    logger.exception(f"Error extending heartbeat for job {job_id}")
                    break

        hb_thread = threading.Thread(target=_heartbeat_runner, daemon=True)
        hb_thread.start()

        staged_artifact_keys: list[str] = []

        try:
            # 1. Revalidate creator permission
            with self.worker_session_factory() as v_session:
                is_valid = revalidate_job_creator(
                    v_session, job_id, attempt_token, lease_generation
                )
            if not is_valid:
                logger.warning(f"Creator permissions revoked for job {job_id}; failing attempt")
                with self.worker_session_factory() as f_session:
                    fail_job(
                        f_session,
                        job_id,
                        self.worker_id,
                        attempt_token,
                        lease_generation,
                        error_code="creator_membership_revoked",
                        error_summary="Job creator no longer has active organisation membership",
                        retryable=False,
                    )
                return

            # Establish tenant context for data-plane operations
            tenant_ctx = TenantContext(
                organisation_id=org_id,
                principal_id=1,  # Worker operates within organisation boundary
                role=Role.ADMIN,
                request_id=f"job_attempt_{attempt_token[:8]}",
            )

            # 2. Stage: ingesting
            with self.worker_session_factory() as s:
                transition_job_stage(
                    s, job_id, self.worker_id, attempt_token, lease_generation, "ingesting"
                )

            # Fetch run and uploaded input files under tenant isolation
            with UnitOfWork(self.app_session_factory, tenant_ctx) as uow:
                assert uow.session is not None
                run = get_run_by_id(uow.session, tenant_ctx, run_id)
                if run is None:
                    raise ValueError(f"Run {run_id} not found for organisation {org_id}")
                run_public_id = run.public_id

                org = get_organisation(uow.session, org_id)
                org_public_id = org.public_id if org else f"org_{org_id}"

                uploaded_files = list_uploaded_files_for_run(uow.session, tenant_ctx, run_id)

            file_map: dict[str, UploadedFileMetadata] = {f.file_role: f for f in uploaded_files}
            required_roles = ("bank_statement", "recon_report", "order_ledger")
            for r in required_roles:
                if r not in file_map:
                    raise InputError(f"Missing required input file: {r}")

            # Retrieve input bytes from storage and verify SHA-256
            input_bytes: dict[str, bytes] = {}
            for role in required_roles:
                meta = file_map[role]
                raw = self.storage.retrieve_bytes(meta.object_key)
                computed_hash = hashlib.sha256(raw).hexdigest()
                if computed_hash != meta.sha256_checksum:
                    raise ValueError(
                        f"Checksum mismatch for {role}: expected {meta.sha256_checksum}, got {computed_hash}"
                    )
                input_bytes[role] = raw

            # Check heartbeat health
            if heartbeat_error.is_set():
                raise JobFencingError("Heartbeat lost before engine execution")

            # 3. Stage: reconciling
            with self.worker_session_factory() as s:
                transition_job_stage(
                    s, job_id, self.worker_id, attempt_token, lease_generation, "reconciling"
                )

            report = reconcile_bytes(
                input_bytes["bank_statement"],
                input_bytes["recon_report"],
                input_bytes["order_ledger"],
            )
            cert_envelope = issue_certificate(report)
            presentation = build_presentation_payload(report, certificate=cert_envelope)
            tally_xml = journal_json_to_tally_xml(
                report.get("journal") or [], company="Your Company Name"
            )

            canonical_bytes = _canonical(report)
            canonical_text = canonical_bytes.decode("utf-8")
            report_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
            content_sha256 = cert_envelope["content_sha256"]

            # 4. Stage: persisting (Artifact staging and S3 promotion)
            with self.worker_session_factory() as s:
                transition_job_stage(
                    s, job_id, self.worker_id, attempt_token, lease_generation, "persisting"
                )

            # Stage artifacts in attempt directory
            tally_bytes = tally_xml.encode("utf-8")
            tally_sha = hashlib.sha256(tally_bytes).hexdigest()
            tally_stage_key = generate_attempt_artifact_key(
                org_public_id, run_public_id, attempt_token, "tally_xml", "xml"
            )
            self.storage.store_bytes(tally_stage_key, tally_bytes, "application/xml")
            staged_artifact_keys.append(tally_stage_key)

            report_stage_key = generate_attempt_artifact_key(
                org_public_id, run_public_id, attempt_token, "report_json", "json"
            )
            self.storage.store_bytes(report_stage_key, canonical_bytes, "application/json")
            staged_artifact_keys.append(report_stage_key)

            cert_bytes = _canonical(cert_envelope["certificate"])
            cert_sha = hashlib.sha256(cert_bytes).hexdigest()
            cert_stage_key = generate_attempt_artifact_key(
                org_public_id, run_public_id, attempt_token, "certificate_json", "json"
            )
            self.storage.store_bytes(cert_stage_key, cert_bytes, "application/json")
            staged_artifact_keys.append(cert_stage_key)

            # Copy from staging to final published keys
            tally_final_key = generate_artifact_object_key(
                org_public_id, run_public_id, "tally_xml", tally_sha, "xml"
            )
            tally_meta = self.storage.copy_object(tally_stage_key, tally_final_key)

            report_final_key = generate_artifact_object_key(
                org_public_id, run_public_id, "report_json", report_sha256, "json"
            )
            report_meta = self.storage.copy_object(report_stage_key, report_final_key)

            cert_final_key = generate_artifact_object_key(
                org_public_id, run_public_id, "certificate_json", cert_sha, "json"
            )
            cert_meta = self.storage.copy_object(cert_stage_key, cert_final_key)

            # Pre-commit cancellation check
            with self.worker_session_factory() as c_session:
                if check_job_cancellation(c_session, job_id, attempt_token, lease_generation):
                    logger.info(f"Job {job_id} cancellation acknowledged before commit")
                    cancel_ack_job(
                        c_session, job_id, self.worker_id, attempt_token, lease_generation
                    )
                    return

            if heartbeat_error.is_set():
                raise JobFencingError("Heartbeat lost before database commit")

            # 5. SINGLE Fenced PostgreSQL completion transaction
            now = datetime.now(UTC)
            with UnitOfWork(self.app_session_factory, tenant_ctx) as uow:
                assert uow.session is not None

                # Save results
                save_result(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    summary_json=report.get("totals") or {},
                    presentation_json=presentation,
                    canonical_report_text=canonical_text,
                    audit_root=report.get("audit_root", ""),
                    report_sha256=report_sha256,
                )

                # Save investigations
                raw_investigations = report.get("investigations") or []
                save_investigations(uow.session, tenant_ctx, run_id, raw_investigations)

                # Save certificate
                save_certificate(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    certificate_json=cert_envelope["certificate"],
                    content_sha256=content_sha256,
                    report_sha256=report_sha256,
                    is_signed=cert_envelope.get("signed", False),
                    signature=cert_envelope.get("signature"),
                    public_key_pem=cert_envelope.get("public_key_pem"),
                )

                # Save promoted artifact metadata records
                save_artifact_metadata(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    artifact_type="tally_xml",
                    filename="untangle_tally_vouchers.xml",
                    media_type="application/xml",
                    size_bytes=len(tally_bytes),
                    content_sha256=tally_sha,
                    backend=tally_meta.backend,
                    object_key=tally_meta.key,
                    lifecycle_state="active",
                    etag=tally_meta.etag,
                    version_id=tally_meta.version_id,
                )
                save_artifact_metadata(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    artifact_type="report_json",
                    filename="untangle_report.json",
                    media_type="application/json",
                    size_bytes=len(canonical_bytes),
                    content_sha256=report_sha256,
                    backend=report_meta.backend,
                    object_key=report_meta.key,
                    lifecycle_state="active",
                    etag=report_meta.etag,
                    version_id=report_meta.version_id,
                )
                save_artifact_metadata(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    artifact_type="certificate_json",
                    filename="untangle_certificate.json",
                    media_type="application/json",
                    size_bytes=len(cert_bytes),
                    content_sha256=cert_sha,
                    backend=cert_meta.backend,
                    object_key=cert_meta.key,
                    lifecycle_state="active",
                    etag=cert_meta.etag,
                    version_id=cert_meta.version_id,
                )

                # Append audit event
                append_audit_event(
                    uow.session,
                    tenant_ctx,
                    event_type="run.completed",
                    subject_type="reconciliation_run",
                    subject_public_id=run_public_id,
                    metadata_json={
                        "report_sha256": report_sha256,
                        "content_sha256": content_sha256,
                        "job_id": job_id,
                    },
                )

                # Complete run
                complete_run(
                    uow.session,
                    tenant_ctx,
                    run_id,
                    reconciliation_hash=report_sha256,
                    bank_statement_hash=hashlib.sha256(input_bytes["bank_statement"]).hexdigest(),
                    recon_report_hash=hashlib.sha256(input_bytes["recon_report"]).hexdigest(),
                    order_ledger_hash=hashlib.sha256(input_bytes["order_ledger"]).hexdigest(),
                    evidence_pack_id=(report.get("config", {}).get("evidence_pack") or {}).get(
                        "pack_id"
                    ),
                    evidence_pack_version=(report.get("config", {}).get("evidence_pack") or {}).get(
                        "version"
                    ),
                    completed_at=now,
                )

                # Attempt-fenced job completion
                complete_job_fenced(
                    uow.session,
                    tenant_ctx,
                    job_id,
                    attempt_token=attempt_token,
                    lease_generation=lease_generation,
                    completed_at=now,
                )

            logger.info(f"Job {job_id} completed successfully for run {run_public_id}")

        except JobFencingError as exc:
            logger.warning(f"Fencing error executing job {job_id}: {exc}")
            # Worker was preempted or lease expired; do not modify DB state
        except InputError as exc:
            logger.error(f"Input validation error executing job {job_id}: {exc}")
            with self.worker_session_factory() as err_session:
                fail_job(
                    err_session,
                    job_id,
                    self.worker_id,
                    attempt_token,
                    lease_generation,
                    error_code="INVALID_INPUT",
                    error_summary=str(exc),
                    retryable=False,
                )
        except Exception as exc:
            logger.exception(f"Error executing job {job_id}: {exc}")
            with self.worker_session_factory() as err_session:
                fail_job(
                    err_session,
                    job_id,
                    self.worker_id,
                    attempt_token,
                    lease_generation,
                    error_code="EXECUTION_FAILURE",
                    error_summary=str(exc),
                    retryable=True,
                )
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=5.0)
            # Cleanup staging attempt artifacts
            for k in staged_artifact_keys:
                try:
                    self.storage.delete_object(k)
                except Exception:
                    pass


BackgroundWorkerService = ReconciliationWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Untangle Background Reconciliation Worker")
    parser.add_argument("--worker-id", type=str, default=None, help="Custom worker identifier")
    parser.add_argument(
        "--lease-seconds", type=int, default=60, help="Lease timeout duration in seconds"
    )
    parser.add_argument(
        "--poll-interval", type=float, default=1.0, help="Polling interval in seconds"
    )
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    app_db_url = get_database_url()
    if not app_db_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    worker_db_url = get_worker_database_url()

    app_engine = create_db_engine(app_db_url)
    app_session_factory = create_session_factory(app_engine)

    worker_engine = create_db_engine(worker_db_url)
    worker_session_factory = create_session_factory(worker_engine)

    storage = get_storage_backend()

    worker = ReconciliationWorker(
        app_session_factory=app_session_factory,
        worker_session_factory=worker_session_factory,
        storage=storage,
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
    )

    if args.once:
        processed = worker.run_once()
        logger.info(f"Run-once completed, processed job: {processed}")
    else:
        logger.info(f"Starting worker {worker.worker_id} polling every {args.poll_interval}s...")
        worker.run_loop(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()

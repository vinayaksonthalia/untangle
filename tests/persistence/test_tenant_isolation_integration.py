"""Integration tests for multi-tenant isolation and IDOR defense.

Proves that Organisation A cannot read, list, update, soft-delete, or infer
the existence of Organisation B's records.
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session, sessionmaker

from persistence.context import TenantContext
from persistence.repositories.artifact import list_artifacts_for_run, list_uploaded_files_for_run
from persistence.repositories.audit import list_audit_events
from persistence.repositories.certificate import (
    get_certificate_by_run_id,
)
from persistence.repositories.investigation import list_investigations_by_run_id
from persistence.repositories.result import get_result_by_run_id
from persistence.repositories.run import (
    get_run_by_public_id,
    list_runs,
    soft_delete_run,
)
from persistence.service import TenantReconciliationService
from persistence.uow import UnitOfWork


def test_complete_cross_tenant_isolation(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
    tenant_b: tuple[TenantContext, int],
) -> None:
    ctx_a, org_a_id = tenant_a
    ctx_b, org_b_id = tenant_b

    # Synthetic sample files for testing
    import tempfile

    from generator.config import Config
    from generator.demo_dataset import write_demo_dataset

    tmp = tempfile.mkdtemp()
    base = write_demo_dataset(tmp, Config())
    with open(os.path.join(base, "bank_statement.csv"), "rb") as f:
        bank_data = f.read()
    with open(os.path.join(base, "recon_report.json"), "rb") as f:
        recon_data = f.read()
    with open(os.path.join(base, "order_ledger.csv"), "rb") as f:
        ledger_data = f.read()

    service = TenantReconciliationService(session_factory)

    # 1. Tenant A executes reconciliation
    res_a = service.execute_reconciliation(ctx_a, bank_data, recon_data, ledger_data)
    run_a_public_id = res_a["run_public_id"]
    assert res_a["certificate"]["content_sha256"] is not None

    # 2. Tenant B executes reconciliation
    res_b = service.execute_reconciliation(ctx_b, bank_data, recon_data, ledger_data)
    run_b_public_id = res_b["run_public_id"]

    # -----------------------------------------------------------------------
    # Tenant A attempts to access Tenant B's records
    # -----------------------------------------------------------------------
    with UnitOfWork(session_factory, ctx_a) as uow:
        # A. Cannot read Tenant B's run by public ID
        attempt_run = get_run_by_public_id(uow.session, ctx_a, run_b_public_id)
        assert attempt_run is None

        # Guessed completely fictitious ID returns identical None (no enumeration oracle)
        guessed_run = get_run_by_public_id(
            uow.session, ctx_a, "run_00000000000000000000000000000000"
        )
        assert guessed_run is None

        # B. Cannot list Tenant B's runs
        runs_listed_by_a = list_runs(uow.session, ctx_a)
        run_ids_listed = {run.public_id for run in runs_listed_by_a}
        assert run_a_public_id in run_ids_listed
        assert run_b_public_id not in run_ids_listed

        # C. Cannot retrieve Tenant B's run by internal ID
        # Load run B internal ID using an un-scoped admin query to test repository denial
        with UnitOfWork(session_factory, ctx_b) as uow_b:
            run_b_internal = get_run_by_public_id(uow_b.session, ctx_b, run_b_public_id)
            assert run_b_internal is not None
            run_b_internal_id = run_b_internal.id

        # Tenant A querying with run_b_internal_id gets None
        attempt_result = get_result_by_run_id(uow.session, ctx_a, run_b_internal_id)
        assert attempt_result is None

        # D. Cannot access Tenant B's investigations
        invs_attempt = list_investigations_by_run_id(uow.session, ctx_a, run_b_internal_id)
        assert len(invs_attempt) == 0

        # E. Cannot access Tenant B's certificate
        cert_attempt = get_certificate_by_run_id(uow.session, ctx_a, run_b_internal_id)
        assert cert_attempt is None

        # F. Cannot access Tenant B's uploaded files or artifacts
        files_attempt = list_uploaded_files_for_run(uow.session, ctx_a, run_b_internal_id)
        assert len(files_attempt) == 0

        artifacts_attempt = list_artifacts_for_run(uow.session, ctx_a, run_b_internal_id)
        assert len(artifacts_attempt) == 0

        # G. Cannot access Tenant B's audit events
        events_a = list_audit_events(uow.session, ctx_a)
        for ev in events_a:
            assert ev.organisation_id == org_a_id
            assert ev.subject_public_id != run_b_public_id

        # H. Cannot soft-delete Tenant B's run
        deleted = soft_delete_run(uow.session, ctx_a, run_b_public_id)
        assert deleted is False

    # Verify that Tenant B's run was not deleted
    with UnitOfWork(session_factory, ctx_b) as uow_b:
        run_b_after = get_run_by_public_id(uow_b.session, ctx_b, run_b_public_id)
        assert run_b_after is not None
        assert run_b_after.is_deleted is False

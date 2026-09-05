"""Deterministic round-trip fidelity tests.

Proves that canonical report bytes, integer paise, and SHA-256 digests
are preserved byte-identically through database persistence.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session, sessionmaker

from engine.certificate import _canonical
from persistence.context import TenantContext
from persistence.repositories.result import get_result_by_run_id, save_result
from persistence.repositories.run import create_run
from persistence.uow import UnitOfWork


def test_reconciliation_result_deterministic_round_trip(
    session_factory: sessionmaker[Session],
    tenant_a: tuple[TenantContext, int],
) -> None:
    ctx, org_id = tenant_a

    # Construct report with diverse Unicode, zero-width chars, and large integer paise
    original_report = {
        "totals": {
            "reconciled_count": 142,
            "total_credits_paise": 9_123_456_789_012_345,  # ~91 lakh crore paise
            "fee_gst_recoverable_paise": 1_234_567_890,
            "settled_slice_paise": -450000,
        },
        "config": {
            "evidence_pack_id": "in.untangle.narration.default@1.0.0",
            "seed": 42,
            "threshold": 0.85,
        },
        "attributions": [
            {
                "line_key": "key_unicode_001",
                "rail": "razorpay_settlement",
                "narration_sample": "UPI/Razorpay/व्यापारी/Payment/₹1500",
                "amount_paise": 150000,
            }
        ],
        "audit_root": "e" * 64,
    }

    canonical_bytes = _canonical(original_report)
    canonical_text = canonical_bytes.decode("utf-8")
    expected_sha256 = hashlib.sha256(canonical_bytes).hexdigest()

    with UnitOfWork(session_factory, ctx) as uow:
        run = create_run(uow.session, ctx)
        run_id = run.id

        saved = save_result(
            uow.session,
            ctx,
            run_id,
            summary_json=original_report["totals"],
            presentation_json={"summary": original_report["totals"]},
            canonical_report_text=canonical_text,
            audit_root=original_report["audit_root"],
            report_sha256=expected_sha256,
        )
        assert saved.id > 0

    # Retrieve in a new session and verify byte and paise fidelity
    with UnitOfWork(session_factory, ctx) as uow:
        retrieved = get_result_by_run_id(uow.session, ctx, run_id)
        assert retrieved is not None

        # 1. Exact SHA-256 hash preservation
        assert retrieved.report_sha256 == expected_sha256
        assert (
            hashlib.sha256(retrieved.canonical_report_text.encode("utf-8")).hexdigest()
            == expected_sha256
        )

        # 2. Exact byte-for-byte canonical string preservation
        assert retrieved.canonical_report_text == canonical_text

        # 3. Exact integer paise precision (no float conversions or truncation)
        retrieved_dict = json.loads(retrieved.canonical_report_text)
        assert retrieved_dict["totals"]["total_credits_paise"] == 9_123_456_789_012_345
        assert retrieved_dict["totals"]["fee_gst_recoverable_paise"] == 1_234_567_890
        assert retrieved_dict["totals"]["settled_slice_paise"] == -450000

        # 4. Unicode preservation
        assert (
            retrieved_dict["attributions"][0]["narration_sample"]
            == "UPI/Razorpay/व्यापारी/Payment/₹1500"
        )

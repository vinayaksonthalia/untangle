"""Unit and adversarial regression tests for the UI Presentation Contract (Phase 2, Task 2).

Verifies:
1. Operational presentation structure, schema version, and exact integer paise conservation.
2. Complete absence of `line_key`, raw UTRs, raw narration text, account numbers, and server paths.
3. Strict separation of operational presentation (`evaluation: null`) from server-controlled sealed evaluation.
4. Authoritative certificate verification breakdown and failure reasons.
5. Exact schema compatibility, legacy report handling, and fail-closed validation.
6. Bounded, deterministic pagination with global ordinal item IDs.
7. Web API endpoint integration (/api/presentation/sample, /api/presentation, /api/evaluation/sealed).
"""

from __future__ import annotations

import copy
import json
from io import BytesIO

import pytest
from starlette.testclient import TestClient

from engine.certificate import issue_certificate
from engine.service import reconcile_bytes
from eval.benchmark_generator import (
    _format_bank_statement_csv,
    _format_order_ledger_csv,
    _format_recon_json,
)
from generator import bank as BANK
from generator import build as B
from generator import config as C
from generator import noise as NOISE
from webapp.app import app
from webapp.presentation import (
    PRESENTATION_SCHEMA_VERSION,
    PresentationSchemaError,
    build_presentation_payload,
    build_sealed_evaluation_presentation,
)


@pytest.fixture
def sample_report_and_cert():
    cfg = C.Config(seed=42, scale=1.0)
    built = B.build(cfg)
    bank_data, _ = BANK.build_bank_and_truth(cfg, built)
    ledger_data, _ = NOISE.corrupt_ledger(cfg, built["orders"])
    b_bytes = _format_bank_statement_csv(bank_data)
    r_bytes = _format_recon_json(built["recon_rows"])
    l_bytes = _format_order_ledger_csv(ledger_data)

    report = reconcile_bytes(b_bytes, r_bytes, l_bytes, seed=42)
    cert = issue_certificate(report)
    return report, cert, bank_data


# ============================================================================
# 1. Operational Presentation Structure & Invariants
# ============================================================================


def test_presentation_payload_structure(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert
    presentation = build_presentation_payload(report, certificate=cert)

    assert presentation["presentation_schema_version"] == PRESENTATION_SCHEMA_VERSION
    assert presentation["contract_type"] == "reconciliation_presentation"
    assert presentation["evaluation"] is None

    # Run Identity
    assert presentation["run_identity"]["report_schema_version"] == "1.1.0"
    assert presentation["run_identity"]["legacy"] is False
    assert presentation["run_identity"]["audit_root"] == report["audit_root"]

    # Evidence Pack
    assert presentation["evidence_pack"]["pack_id"] == "in.untangle.narration.default"
    assert presentation["evidence_pack"]["status"] == "registered"

    # Summary paise agreement
    totals = report["totals"]
    assert presentation["summary"]["n_bank_lines"] == totals["n_bank_lines"]
    assert presentation["summary"]["total_credit_paise"] == totals["total_credit_paise"]
    assert presentation["summary"]["reconciled_paise"] == totals["reconciled_paise"]
    assert presentation["summary"]["reconciled_count"] == totals["reconciled_count"]
    assert presentation["summary"]["fee_gst_recoverable_paise"] == totals["fee_gst_recoverable_paise"]

    # Rails
    assert len(presentation["rails"]) == 6
    total_bps = sum(r["share_basis_points"] for r in presentation["rails"])
    assert 9990 <= total_bps <= 10010  # Rounded basis points sum to ~10000

    # Certificate Status
    assert presentation["certificate_status"]["status"] == "verified"
    assert presentation["certificate_status"]["hash_bound"] is True
    assert presentation["certificate_status"]["report_binding_valid"] is True
    assert presentation["certificate_status"]["evidence_pack_valid"] is True
    assert presentation["certificate_status"]["failure_reasons"] == []


# ============================================================================
# 2. Strict Redaction & No Sensitive Data Leakage
# ============================================================================


def test_no_line_key_in_public_verdicts(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert
    presentation = build_presentation_payload(report, certificate=cert)

    items = presentation["line_verdicts"]["items"]
    assert len(items) > 0
    for it in items:
        assert "line_key" not in it, f"Internal line_key leaked in item {it}"
        assert it["item_id"].startswith("item_")


def test_sensitive_tokens_redacted(sample_report_and_cert):
    report, cert, bank_data = sample_report_and_cert
    presentation = build_presentation_payload(report, certificate=cert)
    serialized = json.dumps(presentation)

    # Collect known raw sensitive strings from statement
    raw_narrations = [row["narration"] for row in bank_data if len(row.get("narration", "")) > 10]
    raw_bank_refs = [row["bank_ref"] for row in bank_data if row.get("bank_ref")]

    # Check that raw narrations do not appear in serialized presentation
    for narr in raw_narrations[:20]:
        assert narr not in serialized, f"Raw narration leaked: {narr}"

    # Check that raw 16-char UTR bank refs do not appear in serialized presentation
    for ref in raw_bank_refs[:20]:
        assert ref not in serialized, f"Raw UTR reference leaked: {ref}"

    # Check that filesystem server paths do not appear
    assert "/Users/" not in serialized
    assert "/tmp/" not in serialized
    assert "data/bank_statement.csv" not in serialized


# ============================================================================
# 3. Bounded & Deterministic Pagination
# ============================================================================


def test_pagination_bounds_and_global_ordinals(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert

    # Page 1: limit 50, offset 0
    p1 = build_presentation_payload(report, certificate=cert, limit=50, offset=0)
    assert p1["line_verdicts"]["total"] == len(report["attributions"])
    assert p1["line_verdicts"]["limit"] == 50
    assert p1["line_verdicts"]["offset"] == 0
    assert p1["line_verdicts"]["has_more"] is True
    assert len(p1["line_verdicts"]["items"]) == 50
    assert p1["line_verdicts"]["items"][0]["item_id"] == "item_0001"
    assert p1["line_verdicts"]["items"][49]["item_id"] == "item_0050"

    # Page 2: limit 50, offset 50 -> item_ids continue from item_0051
    p2 = build_presentation_payload(report, certificate=cert, limit=50, offset=50)
    assert p2["line_verdicts"]["offset"] == 50
    assert p2["line_verdicts"]["items"][0]["item_id"] == "item_0051"
    assert p2["line_verdicts"]["items"][49]["item_id"] == "item_0100"

    # Limit capped at MAX_VERDICTS_LIMIT (100)
    p_capped = build_presentation_payload(report, certificate=cert, limit=500, offset=0)
    assert p_capped["line_verdicts"]["limit"] == 100
    assert len(p_capped["line_verdicts"]["items"]) == 100


def test_pagination_invalid_parameters(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert

    with pytest.raises(PresentationSchemaError, match="Invalid pagination limit"):
        build_presentation_payload(report, certificate=cert, limit=0)

    with pytest.raises(PresentationSchemaError, match="Invalid pagination limit"):
        build_presentation_payload(report, certificate=cert, limit=-10)

    with pytest.raises(PresentationSchemaError, match="Invalid pagination offset"):
        build_presentation_payload(report, certificate=cert, offset=-5)

    with pytest.raises(PresentationSchemaError, match="Invalid pagination limit"):
        build_presentation_payload(report, certificate=cert, limit=True)  # type: ignore


# ============================================================================
# 4. Authoritative Certificate Verification Breakdown
# ============================================================================


def test_certificate_states_and_failure_reasons(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert

    # 1. Absent certificate
    p_absent = build_presentation_payload(report, certificate=None)
    assert p_absent["certificate_status"]["status"] == "absent"
    assert p_absent["certificate_status"]["hash_bound"] is False
    assert p_absent["certificate_status"]["failure_reasons"] == []

    # 2. Tampered content hash
    tampered_cert = copy.deepcopy(cert)
    tampered_cert["content_sha256"] = "0" * 64
    p_tampered = build_presentation_payload(report, certificate=tampered_cert)
    assert p_tampered["certificate_status"]["status"] == "failed"
    assert "content_hash_mismatch" in p_tampered["certificate_status"]["failure_reasons"]

    # 3. Report binding mismatch (certificate created for different report)
    different_report = copy.deepcopy(report)
    different_report["totals"]["total_credit_paise"] += 100000
    p_mismatch = build_presentation_payload(different_report, certificate=cert)
    assert p_mismatch["certificate_status"]["status"] == "failed"
    assert "report_binding_mismatch" in p_mismatch["certificate_status"]["failure_reasons"]

    # 4. Evidence pack mismatch
    tampered_pack_cert = copy.deepcopy(cert)
    tampered_pack_cert["certificate"]["evidence_pack"]["version"] = "9.9.9"
    # Re-hash certificate body
    body = json.dumps(tampered_pack_cert["certificate"], sort_keys=True, separators=(",", ":")).encode()
    import hashlib
    tampered_pack_cert["content_sha256"] = hashlib.sha256(body).hexdigest()
    p_pack_mismatch = build_presentation_payload(report, certificate=tampered_pack_cert)
    assert p_pack_mismatch["certificate_status"]["status"] == "failed"
    assert "evidence_pack_mismatch" in p_pack_mismatch["certificate_status"]["failure_reasons"]


# ============================================================================
# 5. Schema Compatibility, Fail-Closed, and Legacy Handling
# ============================================================================


def test_unsupported_and_malformed_report_schemas(sample_report_and_cert):
    report, cert, _ = sample_report_and_cert

    # Unsupported future schema version
    bad_schema_report = copy.deepcopy(report)
    bad_schema_report["config"]["report_schema_version"] = "2.0.0"
    with pytest.raises(PresentationSchemaError, match="Unsupported report schema version"):
        build_presentation_payload(bad_schema_report)

    # Malformed non-dictionary report
    with pytest.raises(PresentationSchemaError, match="Report must be a dictionary"):
        build_presentation_payload(["not", "a", "dict"])  # type: ignore

    # Missing totals
    missing_totals = copy.deepcopy(report)
    del missing_totals["totals"]
    with pytest.raises(PresentationSchemaError, match="missing or invalid 'totals'"):
        build_presentation_payload(missing_totals)

    # Non-integer totals field
    corrupt_totals = copy.deepcopy(report)
    corrupt_totals["totals"]["reconciled_paise"] = "2969512363"  # string instead of int
    with pytest.raises(PresentationSchemaError, match="non-integer field"):
        build_presentation_payload(corrupt_totals)


def test_legacy_report_conversion():
    """Verify that a valid pre-1.1.0 legacy report without schema version converts cleanly."""
    legacy_report = {
        "totals": {
            "n_bank_lines": 10,
            "total_credit_paise": 1000000,
            "attributed": 8,
            "abstained": 2,
            "reconciled_count": 5,
            "reconciled_paise": 500000,
            "fee_gst_recoverable_paise": 10000,
            "by_rail_count": {"razorpay_settlement": 5, "UNKNOWN": 2, "direct_upi": 3},
            "by_rail_paise": {"razorpay_settlement": 500000, "UNKNOWN": 200000, "direct_upi": 300000},
        },
        "attributions": [
            {"line_key": "k1", "rail": "razorpay_settlement", "confidence": 0.95, "tier": "A", "evidence": []},
            {"line_key": "k2", "rail": "UNKNOWN", "confidence": 0.0, "tier": "none", "abstained": True, "evidence": []},
        ],
    }
    presentation = build_presentation_payload(legacy_report)
    assert presentation["run_identity"]["legacy"] is True
    assert presentation["run_identity"]["report_schema_version"] == "legacy"
    assert presentation["evidence_pack"] is None
    assert presentation["summary"]["total_credit_paise"] == 1000000


# ============================================================================
# 6. Server-Controlled Sealed Evaluation Benchmark
# ============================================================================


def test_sealed_evaluation_presentation():
    """Verify server-authenticated sealed evaluation presentation payload."""
    eval_pres = build_sealed_evaluation_presentation()

    assert eval_pres["presentation_schema_version"] == PRESENTATION_SCHEMA_VERSION
    assert eval_pres["contract_type"] == "sealed_evaluation_presentation"
    assert eval_pres["evaluation_status"] == "verified_server_holdout"
    assert eval_pres["protocol"] == "E3"
    assert eval_pres["dataset_type"] == "synthetic_adversarial_holdout"
    assert eval_pres["seed"] == 1337
    assert "disclaimer" in eval_pres
    assert eval_pres["metrics"]["razorpay_precision"] == 1.0
    assert eval_pres["metrics"]["decoy_false_positives"] == 0
    assert eval_pres["metrics"]["ece_calibration"] <= 0.10


def test_sealed_evaluation_fails_closed_on_missing_manifest(tmp_path):
    """Verify sealed evaluation fails closed if manifest is missing."""
    with pytest.raises(PresentationSchemaError, match="Sealed manifest not found"):
        build_sealed_evaluation_presentation(sealed_dir=str(tmp_path))


# ============================================================================
# 7. Web API Endpoints Integration
# ============================================================================


def test_api_presentation_sample_endpoint():
    client = TestClient(app)
    resp = client.get("/api/presentation/sample?limit=50&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["contract_type"] == "reconciliation_presentation"
    assert data["line_verdicts"]["limit"] == 50
    assert data["evaluation"] is None


def test_api_evaluation_sealed_endpoint():
    client = TestClient(app)
    resp = client.get("/api/evaluation/sealed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["contract_type"] == "sealed_evaluation_presentation"
    assert data["evaluation_status"] == "verified_server_holdout"
    assert data["metrics"]["razorpay_precision"] == 1.0


def test_api_presentation_upload_endpoint(sample_report_and_cert):
    _, _, bank_data = sample_report_and_cert
    cfg = C.Config(seed=42, scale=1.0)
    built = B.build(cfg)
    ledger_data, _ = NOISE.corrupt_ledger(cfg, built["orders"])

    b_csv = _format_bank_statement_csv(bank_data)
    r_json = _format_recon_json(built["recon_rows"])
    l_csv = _format_order_ledger_csv(ledger_data)

    client = TestClient(app)
    resp = client.post(
        "/api/presentation?limit=20&offset=0",
        files={
            "bank": ("bank_statement.csv", BytesIO(b_csv), "text/csv"),
            "recon": ("recon_report.json", BytesIO(r_json), "application/json"),
            "ledger": ("order_ledger.csv", BytesIO(l_csv), "text/csv"),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["contract_type"] == "reconciliation_presentation"
    assert data["summary"]["total_credit_paise"] > 0
    assert len(data["line_verdicts"]["items"]) == 20

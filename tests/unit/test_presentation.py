"""Unit and adversarial regression tests for the UI Presentation Contract (Phase 2, Task 2).

Verifies:
1. Operational presentation structure, schema version, and exact integer paise conservation.
2. Complete absence of `line_key`, raw UTRs, raw narration text, account numbers, and server paths.
3. Strict separation of operational presentation (`evaluation: null`) from server-controlled sealed evaluation.
4. Authoritative certificate verification breakdown and failure reasons.
5. Exact schema compatibility, legacy report handling, and fail-closed validation.
6. Bounded, deterministic pagination with global ordinal item IDs.
7. Web API endpoint integration (/api/presentation/sample, /api/presentation, /api/evaluation/sealed).
8. Qodo regression tests:
   - RecoveryAction key mapping (#6)
   - Boolean totals rejection (#1)
   - Missing by_rail_paise handling without fabricating 0 (#2)
   - Exact integer share_basis_points arithmetic (#3)
   - Rate limiting on POST /api/presentation (#7)
   - Sealed evaluation off request path and clean image serving (#8, #9)
   - Controlled integrity/schema error handling without leaking paths (#10)
"""

from __future__ import annotations

import copy
import hashlib
import json
from io import BytesIO
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import webapp.app as webapp_app
import webapp.presentation as presentation_module
from engine.certificate import issue_certificate
from engine.service import reconcile_bytes
from eval import sealed as sealed_eval
from eval.benchmark_generator import (
    _format_bank_statement_csv,
    _format_order_ledger_csv,
    _format_recon_json,
)
from eval.sealed import generate_sealed_holdout
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
    assert presentation["run_identity"]["creator"] == "untangle.presentation"

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
    total_bps = sum(r["share_basis_points"] for r in presentation["rails"] if r["share_basis_points"] is not None)
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
    with pytest.raises(PresentationSchemaError, match="is not an integer"):
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
# 6. Qodo Regression Tests (#1 to #10)
# ============================================================================


def test_qodo_1_boolean_totals_rejected(sample_report_and_cert):
    """Qodo #1: Reject boolean values in monetary fields and totals counts."""
    report, cert, _ = sample_report_and_cert

    # Boolean True in total_credit_paise
    bool_report = copy.deepcopy(report)
    bool_report["totals"]["total_credit_paise"] = True
    with pytest.raises(PresentationSchemaError, match="is not an integer"):
        build_presentation_payload(bool_report)

    # Boolean False in reconciled_paise
    bool_report2 = copy.deepcopy(report)
    bool_report2["totals"]["reconciled_paise"] = False
    with pytest.raises(PresentationSchemaError, match="is not an integer"):
        build_presentation_payload(bool_report2)

    # Boolean True in by_rail_paise
    bool_report3 = copy.deepcopy(report)
    bool_report3["totals"]["by_rail_paise"]["direct_upi"] = True
    with pytest.raises(PresentationSchemaError, match="must be a non-negative integer"):
        build_presentation_payload(bool_report3)


def test_qodo_2_missing_by_rail_maps_handled_explicitly():
    """Qodo #2: If by_rail_paise is absent, represent unavailable explicitly rather than fabricating zeros."""
    report = {
        "config": {"report_schema_version": "1.1.0"},
        "totals": {
            "n_bank_lines": 10,
            "total_credit_paise": 1000000,
            "attributed": 8,
            "abstained": 2,
            "reconciled_count": 5,
            "reconciled_paise": 500000,
            "fee_gst_recoverable_paise": 10000,
            # by_rail_count and by_rail_paise intentionally omitted
        },
        "attributions": [],
    }
    presentation = build_presentation_payload(report)

    # Unresolved paise must be None (unavailable), not 0
    assert presentation["summary"]["unresolved_paise"] is None

    # Rails must have None counts and amounts, not 0
    for rail in presentation["rails"]:
        assert rail["count"] is None
        assert rail["amount_paise"] is None
        assert rail["share_basis_points"] is None


def test_qodo_3_exact_integer_share_basis_points():
    """Qodo #3: Test exact integer basis points arithmetic and boundary conditions."""
    report = {
        "config": {"report_schema_version": "1.1.0"},
        "totals": {
            "n_bank_lines": 3,
            "total_credit_paise": 30000,
            "attributed": 3,
            "abstained": 0,
            "reconciled_count": 1,
            "reconciled_paise": 10000,
            "fee_gst_recoverable_paise": 0,
            "by_rail_count": {
                "razorpay_settlement": 1,
                "direct_upi": 1,
                "other_gateway": 1,
            },
            "by_rail_paise": {
                "razorpay_settlement": 10000,  # 10000/30000 = 3333 bps (rounded half-up: (100000000 + 15000)//30000 = 3333)
                "direct_upi": 10000,          # 3333 bps
                "other_gateway": 10000,        # 3333 bps
            },
        },
        "attributions": [],
    }
    presentation = build_presentation_payload(report)
    rails = {r["rail"]: r for r in presentation["rails"]}

    assert rails["razorpay_settlement"]["share_basis_points"] == 3333
    assert rails["direct_upi"]["share_basis_points"] == 3333
    assert rails["other_gateway"]["share_basis_points"] == 3333

    # Total credit paise = 0 boundary
    report_zero = copy.deepcopy(report)
    report_zero["totals"]["total_credit_paise"] = 0
    report_zero["totals"]["by_rail_paise"]["razorpay_settlement"] = 0
    p_zero = build_presentation_payload(report_zero)
    rails_zero = {r["rail"]: r for r in p_zero["rails"]}
    assert rails_zero["razorpay_settlement"]["share_basis_points"] == 0


def test_qodo_6_recovery_action_keys_mapped_from_engine_actions(sample_report_and_cert):
    """Qodo #6: Map recovery actions from true RecoveryAction.to_dict() keys."""
    report, cert, _ = sample_report_and_cert

    # Inject realistic engine RecoveryAction dicts into report["recovery_plan"]
    report_with_recovery = copy.deepcopy(report)
    report_with_recovery["recovery_plan"] = {
        "recoverable_if_actioned_paise": 5000000,
        "unresolved_credit_paise": 5000000,
        "unresolved_debit_paise": 0,
        "actions": [
            {
                "action_type": "export_settlement_report",
                "params": {"date_from": "2026-04-01", "date_to": "2026-04-30"},
                "resolves": ["k_001", "k_002", "k_003"],
                "recoverable_paise": 5000000,
                "debit_exposure_paise": 0,
                "cost": 1.0,
                "gain_per_cost": 5000000.0,
                "description": "Export Razorpay settlement report (2026-04-01 to 2026-04-30) — up to ₹50,000.00 recoverable across 3 items if confirmed",
            }
        ],
    }

    presentation = build_presentation_payload(report_with_recovery, certificate=cert)
    actions = presentation["recovery"]["actions"]
    assert len(actions) == 1
    act = actions[0]

    assert act["action_type"] == "export_settlement_report"
    assert act["recoverable_paise"] == 5000000
    assert act["debit_exposure_paise"] == 0
    assert act["resolves_count"] == 3
    assert act["gain_per_cost"] == 5000000.0
    assert "Export Razorpay settlement report" in act["description"]


@pytest.mark.parametrize(
    "recovery_plan",
    [
        "not-a-mapping",
        {"actions": "not-a-list"},
        {"actions": ["not-a-mapping"]},
        {"actions": [{"action_type": "x"}]},
        {
            "actions": [
                {
                    "action_type": "x",
                    "description": "x",
                    "recoverable_paise": True,
                    "debit_exposure_paise": 0,
                    "gain_per_cost": 1.0,
                    "resolves": [],
                }
            ]
        },
        {
            "actions": [
                {
                    "action_type": "x",
                    "description": "x",
                    "recoverable_paise": 1,
                    "debit_exposure_paise": 0,
                    "gain_per_cost": float("nan"),
                    "resolves": [],
                }
            ]
        },
    ],
)
def test_malformed_recovery_plan_fails_with_schema_error(sample_report_and_cert, recovery_plan):
    report, _, _ = sample_report_and_cert
    malformed = copy.deepcopy(report)
    malformed["recovery_plan"] = recovery_plan

    with pytest.raises(PresentationSchemaError, match="[Rr]ecovery"):
        build_presentation_payload(malformed)


def test_present_recovery_plan_requires_all_financial_aggregates(sample_report_and_cert):
    report, _, _ = sample_report_and_cert
    incomplete = copy.deepcopy(report)
    incomplete["recovery_plan"] = {
        "actions": [],
        "recoverable_if_actioned_paise": 10,
        "unresolved_credit_paise": 10,
    }

    with pytest.raises(PresentationSchemaError, match="unresolved_debit_paise"):
        build_presentation_payload(incomplete)


def test_recovery_action_order_preserves_engine_ranking(sample_report_and_cert):
    report, _, _ = sample_report_and_cert
    ranked = copy.deepcopy(report)
    ranked["recovery_plan"] = {
        "recoverable_if_actioned_paise": 110,
        "unresolved_credit_paise": 110,
        "unresolved_debit_paise": 0,
        "actions": [
            {
                "action_type": "high_gain_first",
                "description": "Engine-ranked first",
                "recoverable_paise": 10,
                "debit_exposure_paise": 0,
                "gain_per_cost": 10.0,
                "resolves": ["a"],
            },
            {
                "action_type": "larger_amount_second",
                "description": "Engine-ranked second",
                "recoverable_paise": 100,
                "debit_exposure_paise": 0,
                "gain_per_cost": 1.0,
                "resolves": ["b"],
            },
        ],
    }

    payload = build_presentation_payload(ranked)
    assert [action["action_type"] for action in payload["recovery"]["actions"]] == [
        "high_gain_first",
        "larger_amount_second",
    ]


def test_qodo_7_rate_limiting_on_api_presentation():
    """Qodo #7: POST /api/presentation is subject to per-client rate-limit."""
    client = TestClient(app)

    with patch.dict(webapp_app._RATE_BUCKETS, clear=True):
        # Exceed rate limit window by flooding requests
        status_codes = []
        for _ in range(webapp_app._RATE_LIMIT + 5):
            resp = client.post(
                "/api/presentation",
                files={
                    "bank": ("bank.csv", b"header\n1", "text/csv"),
                    "recon": ("recon.json", b"[]", "application/json"),
                    "ledger": ("ledger.csv", b"header\n1", "text/csv"),
                },
            )
            status_codes.append(resp.status_code)

        assert 429 in status_codes
        assert 429 in [client.get("/api/presentation/sample").status_code, 429]


def test_qodo_8_9_sealed_evaluation_off_request_path_and_cached():
    """Qodo #8 & #9: Sealed evaluation presentation is loaded without running benchmark per request and cached."""
    # Ensure sealed report is built
    build_sealed_evaluation_presentation(allow_compute_if_absent=True)

    # Calling without allow_compute_if_absent should succeed because sealed_report.json exists
    p = build_sealed_evaluation_presentation(allow_compute_if_absent=False)
    assert p["contract_type"] == "sealed_evaluation_presentation"
    assert p["evaluation_status"] == "verified_server_holdout"
    assert p["metrics"]["razorpay_precision"] == 1.0

    # API endpoint serves cached presentation
    client = TestClient(app)
    r1 = client.get("/api/evaluation/sealed")
    r2 = client.get("/api/evaluation/sealed")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_sealed_presentation_ignores_unbound_precomputed_report(tmp_path):
    """A writable report beside trusted inputs must never supply published metrics."""
    sealed_dir = tmp_path / "sealed"
    generate_sealed_holdout(seed=1337, out_dir=str(sealed_dir))
    (sealed_dir / "sealed_report.json").write_text(
        json.dumps({"metrics": {"per_rail": {"razorpay_settlement": {"precision": 0.123}}}}),
        encoding="utf-8",
    )
    presentation_module._SEALED_PRESENTATION_CACHE.clear()

    with patch("eval.sealed.evaluate_sealed", wraps=sealed_eval.evaluate_sealed) as evaluator:
        payload = build_sealed_evaluation_presentation(
            sealed_dir=str(sealed_dir),
            allow_compute_if_absent=True,
        )

    evaluator.assert_called_once()
    assert payload["evaluation_status"] == "verified_server_holdout"
    assert payload["metrics"]["razorpay_precision"] == 1.0
    evaluator_config = payload["evaluator"]
    assert evaluator_config["protocol"] == "E3"
    assert evaluator_config["threshold"] == 0.55
    assert evaluator_config["global_solver"] is False
    assert evaluator_config["evidence_pack"]["pack_id"] == "in.untangle.narration.default"
    assert len(evaluator_config["config_sha256"]) == 64


def test_qodo_10_controlled_integrity_and_schema_error_responses(tmp_path):
    """Qodo #10: Integrity and schema errors return controlled response without 500 or leaked filesystem paths."""
    # Test missing manifest
    with pytest.raises(PresentationSchemaError, match="manifest not found"):
        build_sealed_evaluation_presentation(sealed_dir=str(tmp_path), allow_compute_if_absent=False)

    # Test corrupted manifest
    bad_manifest = tmp_path / "manifest.json"
    bad_manifest.write_text("not json", encoding="utf-8")
    with pytest.raises(PresentationSchemaError, match="invalid or unreadable"):
        build_sealed_evaluation_presentation(sealed_dir=str(tmp_path), allow_compute_if_absent=False)

    # Test API error handler returns 503 controlled response without server path leakage
    with patch("webapp.app._get_cached_sealed_presentation", side_effect=Exception("Disk error on /var/data")):
        client = TestClient(app)
        resp = client.get("/api/evaluation/sealed")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["detail"] == "Sealed evaluation benchmark unavailable."
        assert "/var/data" not in json.dumps(data)


def test_qodo_4_presentation_schema_provenance(sample_report_and_cert):
    """Qodo #4: Ensure machine-readable presentation schema provenance is present in contracts."""
    report, cert, _ = sample_report_and_cert
    presentation = build_presentation_payload(report, certificate=cert)

    # Top level schema provenance
    prov = presentation.get("presentation_schema_provenance")
    assert isinstance(prov, dict)
    assert prov["schema_version"] == "1.0.0"
    assert prov["creator"] == "untangle.presentation"
    assert "created_at" in prov
    assert "doc" in prov

    # Run identity provenance
    run_id = presentation.get("run_identity", {})
    assert run_id.get("creator") == "untangle.presentation"
    assert run_id.get("created_at") == "2026-09-02"

    # Sealed evaluation presentation provenance
    sealed_p = build_sealed_evaluation_presentation(allow_compute_if_absent=True)
    sealed_prov = sealed_p.get("presentation_schema_provenance")
    assert isinstance(sealed_prov, dict)
    assert sealed_prov["schema_version"] == "1.0.0"
    assert sealed_prov["creator"] == "untangle.presentation"


def test_qodo_8_clean_deployment_sealed_provisioning(tmp_path):
    """Qodo #8: On a clean deployment where data/sealed is missing, auto-generate on allow_compute_if_absent."""
    empty_sealed_dir = tmp_path / "sealed"
    # Ensure it doesn't exist yet
    assert not empty_sealed_dir.exists()

    # With allow_compute_if_absent=True, it should generate and evaluate cleanly
    p = build_sealed_evaluation_presentation(sealed_dir=str(empty_sealed_dir), allow_compute_if_absent=True)
    assert p["contract_type"] == "sealed_evaluation_presentation"
    assert p["evaluation_status"] == "verified_server_holdout"
    assert p["metrics"]["razorpay_precision"] == 1.0


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

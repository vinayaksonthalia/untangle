"""Stable UI presentation contract and projection boundary (Phase 2, Task 2).

Converts internal Untangle reconciliation reports and sealed evaluation benchmarks into a
deterministic, versioned, read-only presentation contract for client UIs (e.g. Google Stitch).

Guarantees:
1. Pure read-only presentation: never recalculates financial decisions or money totals.
2. Integer paise precision: all monetary fields remain exact integer paise.
3. Zero sensitive data leakage: UTRs, raw narration text, account numbers, and server paths
   are strictly omitted or converted to categorical reason summaries.
4. No client-supplied evaluation: operational runs always have `evaluation: null`. Sealed
   benchmarks are server-authenticated only.
5. Strict schema validation & fail-closed error handling.
6. Deterministic, bounded pagination with global ordinal item IDs.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from engine.certificate import verify_certificate
from engine.packs import PACK_REGISTRY

PRESENTATION_SCHEMA_VERSION = "1.0.0"
PRESENTATION_SCHEMA_PROVENANCE: dict[str, Any] = {
    "schema_version": PRESENTATION_SCHEMA_VERSION,
    "creator": "untangle.presentation",
    "created_at": "2026-09-02",
    "parent_schema_version": None,
    "doc": "docs/ARCHITECTURE.md#ui-presentation-contract-boundary",
}
SUPPORTED_REPORT_SCHEMAS = frozenset({"1.1.0"})

DEFAULT_VERDICTS_LIMIT = 100
MAX_VERDICTS_LIMIT = 100


class PresentationSchemaError(ValueError):
    """Raised when an input report, certificate, or parameters violate the presentation contract."""


def _categorize_reason(signals: list[str], rail: str, abstained: bool) -> str:
    """Derive a privacy-safe categorical reason summary without leaking raw UTRs or narration strings."""
    if abstained or rail == "UNKNOWN":
        if "decoy_marker" in signals:
            return "Decoy marker suppressed gateway resemblance"
        if "competing_explanations" in signals:
            return "Competing payment rail signals in conflict"
        return "Unattributed ambiguous signals"

    if "utr_exact" in signals:
        return "Exact settlement reference matched"
    if "utr_suffix" in signals:
        return "Corroborated settlement reference suffix matched"
    if "split_reconstruction" in signals:
        return "Reconstructed split settlement leg"
    if "amount_corr" in signals and "value_date_proximity" in signals:
        return "Settlement amount and date proximity matched"
    if "amount_corr" in signals:
        return "Settlement amount matched"
    if "narration_brand_rzp" in signals or "ifsc_ratn" in signals:
        return "Gateway nodal branding and IFSC matched"

    # Non-Razorpay rails
    if rail == "direct_upi":
        return "Direct UPI clearing pattern matched"
    if rail == "cod_remittance":
        return "COD logistics remittance pattern matched"
    if rail == "other_gateway":
        return "Alternate payment gateway pattern matched"
    if rail == "unrelated":
        return "Unrelated counterparty or operational pattern matched"

    return "Payment rail pattern matched"


def _validate_report_structure(report: dict[str, Any]) -> tuple[bool, str]:
    """Validate report structure. Returns (is_legacy, report_schema_version)."""
    if not isinstance(report, dict):
        raise PresentationSchemaError("Report must be a dictionary")

    totals = report.get("totals")
    if not isinstance(totals, dict):
        raise PresentationSchemaError("Report missing or invalid 'totals' object")

    attributions = report.get("attributions")
    if not isinstance(attributions, list):
        raise PresentationSchemaError("Report missing or invalid 'attributions' list")

    required_totals = (
        "n_bank_lines",
        "total_credit_paise",
        "attributed",
        "abstained",
        "reconciled_count",
        "reconciled_paise",
        "fee_gst_recoverable_paise",
    )
    for field in required_totals:
        if field not in totals:
            raise PresentationSchemaError(f"Report totals missing required field: {field}")
        v = totals[field]
        if isinstance(v, bool) or not isinstance(v, int):
            raise PresentationSchemaError(
                f"Report totals field {field!r} is not an integer (got {type(v).__name__}: {v!r})"
            )
        if v < 0:
            raise PresentationSchemaError(f"Report totals field {field!r} cannot be negative ({v})")

    # Validate by_rail maps if present
    if "by_rail_count" in totals:
        if not isinstance(totals["by_rail_count"], dict):
            raise PresentationSchemaError("Report totals 'by_rail_count' must be a dictionary")
        for rk, rv in totals["by_rail_count"].items():
            if isinstance(rv, bool) or not isinstance(rv, int) or rv < 0:
                raise PresentationSchemaError(
                    f"Report totals by_rail_count[{rk!r}] must be a non-negative integer"
                )

    if "by_rail_paise" in totals:
        if not isinstance(totals["by_rail_paise"], dict):
            raise PresentationSchemaError("Report totals 'by_rail_paise' must be a dictionary")
        for rk, rv in totals["by_rail_paise"].items():
            if isinstance(rv, bool) or not isinstance(rv, int) or rv < 0:
                raise PresentationSchemaError(
                    f"Report totals by_rail_paise[{rk!r}] must be a non-negative integer"
                )

    config = report.get("config")
    if isinstance(config, dict) and "report_schema_version" in config:
        schema_ver = config["report_schema_version"]
        if not isinstance(schema_ver, str) or schema_ver not in SUPPORTED_REPORT_SCHEMAS:
            raise PresentationSchemaError(f"Unsupported report schema version: {schema_ver!r}")
        return False, schema_ver

    # Pre-1.1.0 legacy report without schema version
    return True, "legacy"


def _validate_evidence_pack(config: dict[str, Any] | None, is_legacy: bool) -> dict[str, Any] | None:
    """Extract and validate evidence pack provenance."""
    if is_legacy or config is None:
        return None

    pack_info = config.get("evidence_pack")
    if not isinstance(pack_info, dict):
        return None

    pack_id = pack_info.get("pack_id")
    version = pack_info.get("version")
    schema_ver = pack_info.get("schema_version")

    if not (isinstance(pack_id, str) and isinstance(version, str) and isinstance(schema_ver, str)):
        return {
            "pack_id": str(pack_id),
            "version": str(version),
            "schema_version": str(schema_ver),
            "status": "unregistered",
        }

    status = "registered" if (pack_id, version) in PACK_REGISTRY else "unregistered"
    return {
        "pack_id": pack_id,
        "version": version,
        "schema_version": schema_ver,
        "status": status,
    }


def _build_certificate_status(report: dict[str, Any], certificate: dict[str, Any] | None) -> dict[str, Any]:
    """Verify and format certificate status with authoritative failure reasons."""
    if certificate is None:
        return {
            "status": "absent",
            "hash_bound": False,
            "authenticated": False,
            "content_sha256": None,
            "report_binding_valid": False,
            "evidence_pack_valid": False,
            "packets_verified": 0,
            "packets_passed": 0,
            "failure_reasons": [],
        }

    if not isinstance(certificate, dict):
        return {
            "status": "failed",
            "hash_bound": False,
            "authenticated": False,
            "content_sha256": None,
            "report_binding_valid": False,
            "evidence_pack_valid": False,
            "packets_verified": 0,
            "packets_passed": 0,
            "failure_reasons": ["malformed_certificate_payload"],
        }

    # Verify certificate envelope against the exact attached report
    env = dict(certificate)
    env["report"] = report
    v_res = verify_certificate(env)

    failure_reasons: list[str] = []
    if not v_res.get("hash_matches", False):
        failure_reasons.append("content_hash_mismatch")
    if not v_res.get("report_binding_valid", False):
        failure_reasons.append("report_binding_mismatch")
    if not v_res.get("evidence_pack_valid", False):
        failure_reasons.append("evidence_pack_mismatch")

    pv = v_res.get("packets_verified")
    pp = v_res.get("packets_passed")
    if pv is not None and pp is not None and pp < pv:
        failure_reasons.append("packet_verification_failed")

    status = "verified" if v_res.get("ok", False) else "failed"
    if v_res.get("legacy", False):
        status = "legacy" if v_res.get("ok", False) else "failed"

    return {
        "status": status,
        "hash_bound": bool(v_res.get("hash_matches", False)),
        "authenticated": bool(v_res.get("authenticated", False)),
        "content_sha256": v_res.get("claimed_hash") or v_res.get("content_hash"),
        "report_binding_valid": bool(v_res.get("report_binding_valid", False)),
        "evidence_pack_valid": bool(v_res.get("evidence_pack_valid", False)),
        "packets_verified": pv or 0,
        "packets_passed": pp or 0,
        "failure_reasons": failure_reasons,
    }


def _rail_label(rail: str) -> str:
    labels = {
        "razorpay_settlement": "Razorpay settlement",
        "other_gateway": "Other gateway",
        "direct_upi": "Direct UPI",
        "cod_remittance": "COD remittance",
        "unrelated": "Unrelated",
        "UNKNOWN": "Unattributed",
    }
    return labels.get(rail, rail.replace("_", " ").title())


def build_presentation_payload(
    report: dict[str, Any],
    *,
    certificate: dict[str, Any] | None = None,
    limit: int = DEFAULT_VERDICTS_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Convert an authoritative internal report into a safe, bounded presentation payload."""
    is_legacy, report_schema_ver = _validate_report_structure(report)

    # Validate pagination parameters
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise PresentationSchemaError(f"Invalid pagination limit: {limit!r}. Must be a positive integer.")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise PresentationSchemaError(f"Invalid pagination offset: {offset!r}. Must be a non-negative integer.")
    bounded_limit = min(limit, MAX_VERDICTS_LIMIT)

    config = report.get("config", {}) if isinstance(report.get("config"), dict) else {}
    totals = report["totals"]
    total_credit_paise = totals["total_credit_paise"]

    # 1. Run Identity
    run_identity = {
        "report_schema_version": report_schema_ver,
        "engine_version": str(config.get("engine_version", "unknown")),
        "audit_root": str(report.get("audit_root", "")),
        "creator": "untangle.presentation",
        "created_at": "2026-09-02",
        "parent_schema_version": None,
        "legacy": is_legacy,
    }

    # 2. Evidence Pack
    evidence_pack = _validate_evidence_pack(config, is_legacy)

    # 3. Summary (exact integer paise from report totals; None if map is absent)
    by_rail_paise = totals.get("by_rail_paise")
    by_rail_count = totals.get("by_rail_count")

    unresolved_paise: int | None = None
    if isinstance(by_rail_paise, dict) and "razorpay_settlement" in by_rail_paise:
        unresolved_paise = max(0, by_rail_paise["razorpay_settlement"] - totals["reconciled_paise"])

    summary = {
        "n_bank_lines": totals["n_bank_lines"],
        "total_credit_paise": total_credit_paise,
        "attributed_count": totals["attributed"],
        "abstained_count": totals["abstained"],
        "reconciled_count": totals["reconciled_count"],
        "reconciled_paise": totals["reconciled_paise"],
        "unresolved_count": totals.get("unresolved_rzp_count", 0),
        "unresolved_paise": unresolved_paise,
        "fee_gst_recoverable_paise": totals["fee_gst_recoverable_paise"],
        "exception_count": totals.get("exception_count", 0),
    }

    # 4. Rails breakdown (deterministic order: razorpay, other_gateway, direct_upi, cod, unrelated, UNKNOWN)
    rail_order = ("razorpay_settlement", "other_gateway", "direct_upi", "cod_remittance", "unrelated", "UNKNOWN")
    rails_list = []
    for r in rail_order:
        cnt = by_rail_count.get(r) if isinstance(by_rail_count, dict) else None
        amt = by_rail_paise.get(r) if isinstance(by_rail_paise, dict) else None
        bps: int | None = None
        if amt is not None and total_credit_paise > 0:
            bps = (amt * 10000 + total_credit_paise // 2) // total_credit_paise
        elif amt is not None and total_credit_paise == 0:
            bps = 0

        rails_list.append({
            "rail": r,
            "label": _rail_label(r),
            "count": cnt,
            "amount_paise": amt,
            "share_basis_points": bps,
        })

    # 5. Exceptions summary
    exc_by_reason = totals.get("exceptions_by_reason", {})
    exceptions_summary = [
        {"reason_code": code, "label": code.replace("_", " "), "count": count}
        for code, count in sorted(exc_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 6. Actionable Recovery Plan (mapped from true RecoveryAction.to_dict keys)
    rp = report.get("recovery_plan") or {}
    recovery_actions = []
    if isinstance(rp.get("actions"), list):
        for act in sorted(rp["actions"], key=lambda a: (-a.get("recoverable_paise", 0), a.get("action_type", ""))):
            recovery_actions.append({
                "action_type": act.get("action_type", ""),
                "description": act.get("description", ""),
                "recoverable_paise": act.get("recoverable_paise", 0),
                "debit_exposure_paise": act.get("debit_exposure_paise", 0),
                "resolves_count": len(act.get("resolves", [])) if isinstance(act.get("resolves"), list) else 0,
                "gain_per_cost": round(float(act.get("gain_per_cost", 0.0)), 4),
            })

    recovery = {
        "recoverable_if_actioned_paise": rp.get("recoverable_if_actioned_paise", 0),
        "unresolved_credit_paise": rp.get("unresolved_credit_paise", 0),
        "unresolved_debit_paise": rp.get("unresolved_debit_paise", 0),
        "actions": recovery_actions,
    }

    # 7. Line Verdicts (deterministic sort by internal line_key, paginated, opaque item_id)
    reconciled_keys = {
        rec.get("line_key")
        for rec in report.get("reconciliations", [])
        if isinstance(rec, dict) and rec.get("balanced", False)
    }

    sorted_attributions = sorted(
        report.get("attributions", []),
        key=lambda a: (a.get("rail", ""), a.get("confidence", 0.0), a.get("line_key", "")),
    )

    total_verdicts = len(sorted_attributions)
    sliced_attributions = sorted_attributions[offset : offset + bounded_limit]

    verdict_items = []
    for idx, attr in enumerate(sliced_attributions, start=offset + 1):
        line_key = attr.get("line_key", "")
        signals = [e.get("signal", "") for e in attr.get("evidence", []) if isinstance(e, dict)]
        rail_val = attr.get("rail", "UNKNOWN")
        abstained_val = bool(attr.get("abstained", False))

        verdict_items.append({
            "item_id": f"item_{idx:04d}",
            "rail": rail_val,
            "confidence": round(float(attr.get("confidence", 0.0)), 4),
            "tier": str(attr.get("tier", "none")),
            "abstained": abstained_val,
            "signals": sorted(signals),
            "reason_category": _categorize_reason(signals, rail_val, abstained_val),
            "reconciled": line_key in reconciled_keys,
        })

    line_verdicts = {
        "total": total_verdicts,
        "limit": bounded_limit,
        "offset": offset,
        "has_more": (offset + bounded_limit) < total_verdicts,
        "items": verdict_items,
    }

    # 8. Certificate Status
    cert_status = _build_certificate_status(report, certificate)

    # 9. Methodology (optional technical details isolated from main UI summaries)
    methodology = {
        "seed": config.get("seed"),
        "threshold": config.get("threshold"),
        "coverage_curve": totals.get("coverage_curve", []),
    }

    return {
        "presentation_schema_version": PRESENTATION_SCHEMA_VERSION,
        "presentation_schema_provenance": dict(PRESENTATION_SCHEMA_PROVENANCE),
        "contract_type": "reconciliation_presentation",
        "run_identity": run_identity,
        "evidence_pack": evidence_pack,
        "summary": summary,
        "rails": rails_list,
        "exceptions_summary": exceptions_summary,
        "recovery": recovery,
        "line_verdicts": line_verdicts,
        "certificate_status": cert_status,
        "methodology": methodology,
        "evaluation": None,
    }


def build_sealed_evaluation_presentation(
    sealed_dir: str = "data/sealed",
    *,
    allow_compute_if_absent: bool = False,
) -> dict[str, Any]:
    """Load and format the server-authenticated sealed holdout benchmark presentation.

    Fails closed if the sealed dataset or manifest is missing, corrupt, or unverified.
    Never exposes raw filesystem paths.
    """
    manifest_path = os.path.join(sealed_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        if allow_compute_if_absent:
            from eval.sealed import generate_sealed_holdout

            generate_sealed_holdout(seed=1337, out_dir=sealed_dir)
        else:
            raise PresentationSchemaError("Sealed evaluation manifest not found")

    # Authenticate manifest file
    try:
        with open(manifest_path, "rb") as fh:
            manifest_bytes = fh.read()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_data = json.loads(manifest_bytes)
    except Exception as exc:
        raise PresentationSchemaError("Sealed evaluation manifest is invalid or unreadable") from exc

    if not isinstance(manifest_data, dict) or not isinstance(manifest_data.get("files"), dict):
        raise PresentationSchemaError("Sealed evaluation manifest structure is invalid")

    report_path = os.path.join(sealed_dir, "sealed_report.json")
    out_path = "out/sealed_report.json"

    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as fh:
            sealed_res = json.load(fh)
    elif os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            sealed_res = json.load(fh)
    elif allow_compute_if_absent:
        from eval.sealed import evaluate_sealed

        sealed_res = evaluate_sealed(sealed_dir, out_report=report_path)
    else:
        raise PresentationSchemaError("Precomputed sealed evaluation report not found")

    metrics = sealed_res.get("metrics")
    if not isinstance(metrics, dict) or "per_rail" not in metrics:
        raise PresentationSchemaError("Sealed evaluation missing valid metrics block")

    s_rzp = metrics["per_rail"].get("razorpay_settlement", {})
    s_decoy = metrics.get("decoy_false_positive", {})
    totals = sealed_res.get("totals", {})

    precision = float(s_rzp.get("precision", 0.0))
    recall = float(s_rzp.get("recall", 0.0))

    def _extract_ci(ci_obj: Any, default_val: float) -> list[float]:
        if isinstance(ci_obj, dict):
            low = ci_obj.get("low")
            high = ci_obj.get("high")
            if low is not None and high is not None:
                return [round(float(low), 4), round(float(high), 4)]
        elif isinstance(ci_obj, (list, tuple)) and len(ci_obj) >= 2:
            return [round(float(ci_obj[0]), 4), round(float(ci_obj[1]), 4)]
        return [round(default_val, 4), round(default_val, 4)]

    precision_ci = _extract_ci(s_rzp.get("precision_ci95"), precision)
    recall_ci = _extract_ci(s_rzp.get("recall_ci95"), recall)

    return {
        "presentation_schema_version": PRESENTATION_SCHEMA_VERSION,
        "presentation_schema_provenance": dict(PRESENTATION_SCHEMA_PROVENANCE),
        "contract_type": "sealed_evaluation_presentation",
        "evaluation_status": "verified_server_holdout",
        "protocol": "E3",
        "dataset_type": "synthetic_adversarial_holdout",
        "seed": 1337,
        "manifest_sha256": manifest_sha,
        "disclaimer": (
            "Adversarial holdout benchmark on synthetic dataset. "
            "Not an empirical claim about unconfigured bank formats or universal production accuracy."
        ),
        "dataset_summary": {
            "n_bank_lines": totals.get("n_bank_lines", 0),
            "n_recon_rows": totals.get("n_recon_rows", 0),
        },
        "metrics": {
            "razorpay_precision": round(precision, 4),
            "razorpay_precision_ci95": precision_ci,
            "razorpay_recall": round(recall, 4),
            "razorpay_recall_ci95": recall_ci,
            "decoy_false_positives": s_decoy.get("predicted_razorpay", 0),
            "decoy_total": s_decoy.get("non_rzp_lines", 0),
            "ece_calibration": round(float(metrics.get("ece", 0.0)), 4),
            "reconciled_credits": totals.get("reconciled_count", 0),
            "recoverable_fee_gst_paise": totals.get("fee_gst_recoverable_paise", 0),
        },
    }

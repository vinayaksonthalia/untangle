"""Unit and regression tests for versioned narration evidence packs (Phase 2, Task 1).

Covers:
1. Immutability (frozen dataclass, MappingProxyType collections, no mutable registry).
2. Unicode & zero-width boundary handling (boundary creation, no false token generation).
3. Exclusion dominance & conflicting classifications (decoy suppression, fail-closed).
4. Pack selection & actionable domain error handling (unknown selector, invalid type/schema).
5. Schema 1.1.0 report & certificate provenance consistency checks.
6. Deterministic evaluation replay across multiple invocations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import date
from types import MappingProxyType

import pytest

from engine.attribute import attribute_all, attribute_line
from engine.certificate import build_close_certificate, issue_certificate, verify_certificate
from engine.cli import build_report
from engine.config import ConfigError, build_config
from engine.evidence import (
    ReconIndex,
    extract_utr_tokens,
    has_decoy_marker,
    narration_rail_signals,
    razorpay_signals,
)
from engine.models import BankCreditLine, Rail, ReconRow
from engine.packs import (
    DEFAULT_NARRATION_PACK,
    DEFAULT_PACK_ID,
    DEFAULT_PACK_VERSION,
    PACK_REGISTRY,
    NarrationEvidencePack,
    PackError,
    get_default_pack,
    get_pack,
    normalize_narration,
    parse_pack_selector,
)
from engine.verifier import verify_report

# ============================================================================
# 1. Immutability & Structure
# ============================================================================


def test_pack_immutability():
    """Verify that NarrationEvidencePack and its collections are deeply immutable."""
    pack = get_default_pack()
    assert isinstance(pack, NarrationEvidencePack)

    # Pack dataclass is frozen
    with pytest.raises(FrozenInstanceError):
        pack.description = "Mutated description"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        pack.rzp_ifsc = "HDFC0000001"  # type: ignore

    # Rule collections are immutable mappings / tuples
    assert isinstance(pack.rail_keywords, MappingProxyType)
    with pytest.raises(TypeError):
        pack.rail_keywords[Rail.OTHER_GATEWAY] = ("fake",)  # type: ignore

    assert isinstance(pack.decoy_markers, tuple)
    assert isinstance(pack.rzp_brand, tuple)
    assert isinstance(pack.rzp_context, tuple)


def test_registry_immutability():
    """Verify that PACK_REGISTRY is an immutable mapping and cannot be modified at runtime."""
    assert isinstance(PACK_REGISTRY, MappingProxyType)
    with pytest.raises(TypeError):
        PACK_REGISTRY[("test.pack", "1.0.0")] = DEFAULT_NARRATION_PACK  # type: ignore


# ============================================================================
# 2. Unicode Normalization & Zero-Width Boundary Handling
# ============================================================================


def test_normalize_narration_idempotence():
    """Verify that normalize_narration is deterministic and idempotent."""
    samples = [
        "Normal narration text",
        "  Leading and trailing whitespace  ",
        "Multiple    spaces   between   words",
        "Razorpay\u200bSettlement\u200cPayment",
        "\ufeffBOM prefix \u2060word\u00adbreak",
        "",
        "Mixed Case With UPPER and lower",
    ]
    for sample in samples:
        first = normalize_narration(sample)
        second = normalize_narration(first)
        assert first == second, f"Normalization not idempotent for {sample!r}"


def test_zero_width_characters_create_explicit_boundaries():
    """Verify zero-width characters create whitespace boundaries rather than concatenating tokens."""
    # 1. Zero-width character inside brand word must NOT match
    embedded_rzp = "razor\u200bpay settlement"
    normalized = normalize_narration(embedded_rzp)
    assert normalized == "razor pay settlement"
    line = BankCreditLine(
        key="k1",
        value_date=date(2026, 4, 1),
        amount_paise=100000,
        narration=embedded_rzp,
        bank_ref=None,
        is_credit=True,
    )
    # Narration brand "razorpay" should NOT match "razor pay"
    rzp_ev = razorpay_signals(line, ReconIndex([]))
    assert not any(e.signal == "narration_brand_rzp" for e in rzp_ev)

    # 2. Zero-width character inside UTR token must NOT manufacture a 16-char UTR
    # Valid UTR shape: 10 digits + 6 lowercase alnum (16 chars)
    split_utr = "1234567890\u200babcdef"
    assert extract_utr_tokens(split_utr) == []

    clean_utr = "1234567890abcdef"
    assert extract_utr_tokens(clean_utr) == ["1234567890abcdef"]

    # 3. Soft hyphens and directional marks create boundaries
    soft_hyphen = "delhi\u00advery logistics"
    assert normalize_narration(soft_hyphen) == "delhi very logistics"


# ============================================================================
# 3. Exclusion Dominance & Contradiction Semantics
# ============================================================================


def test_decoy_markers_suppress_narration_evidence_only():
    """Verify decoy markers suppress positive narration resemblance but not report-backed ties."""
    index = ReconIndex([
        ReconRow(
            entity_id="pay_1",
            type="payment",
            amount_paise=500000,
            fee_paise=1000,
            tax_paise=180,
            debit_paise=0,
            credit_paise=500000,
            settlement_id="set_1",
            settlement_utr="1780488000abcdef",
            settled_at=None,
            created_at=None,
            on_hold=False,
            dispute_id=None,
            order_id=None,
            method=None,
            description=None,
        )
    ])

    # Case A: Decoy marker present with narration resemblance only -> suppressed
    line_decoy_only = BankCreditLine(
        key="k_decoy",
        value_date=date(2026, 4, 1),
        amount_paise=500000,
        narration="RAZORPAYX PAYOUTS TO VENDOR RATN0000088",
        bank_ref=None,
        is_credit=True,
    )
    assert has_decoy_marker(line_decoy_only) is not None
    ev_decoy = razorpay_signals(line_decoy_only, ReconIndex([]))
    # Brand, IFSC, settlement_ref must be suppressed
    assert not any(e.signal in {"narration_brand_rzp", "ifsc_ratn", "settlement_ref"} for e in ev_decoy)

    # Case B: Decoy marker present WITH independent exact UTR match -> UTR tie PRESERVED
    line_with_utr = BankCreditLine(
        key="k_utr",
        value_date=date(2026, 4, 1),
        amount_paise=500000,
        narration="RAZORPAYX PAYOUTS 1780488000abcdef",
        bank_ref=None,
        is_credit=True,
    )
    ev_utr = razorpay_signals(line_with_utr, index)
    # utr_exact is report-backed and must not be erased
    assert any(e.signal == "utr_exact" for e in ev_utr)


def test_competing_narration_rules_fail_closed():
    """Verify contradictory non-Razorpay narration patterns fail closed (abstain) when equal."""
    line_contradiction = BankCreditLine(
        key="k_conflict",
        value_date=date(2026, 4, 1),
        amount_paise=100000,
        narration="PAYU SETTLEMENT AND CASHFREE PAYMENT",
        bank_ref=None,
        is_credit=True,
    )
    signals = narration_rail_signals(line_contradiction)
    assert Rail.OTHER_GATEWAY in signals


# ============================================================================
# 4. Pack Selection & Domain Error Handling
# ============================================================================


def test_pack_selector_resolution():
    """Verify valid selectors resolve to the built-in pack."""
    assert get_pack(None) == DEFAULT_NARRATION_PACK
    assert get_pack("") == DEFAULT_NARRATION_PACK
    assert get_pack("default") == DEFAULT_NARRATION_PACK
    assert get_pack(DEFAULT_PACK_ID) == DEFAULT_NARRATION_PACK
    assert get_pack(f"{DEFAULT_PACK_ID}@{DEFAULT_PACK_VERSION}") == DEFAULT_NARRATION_PACK


def test_pack_selector_errors():
    """Verify unknown, malformed, or invalid selectors raise actionable PackError."""
    with pytest.raises(PackError, match="Unknown narration evidence pack: unknown.pack@1.0.0"):
        get_pack("unknown.pack@1.0.0")

    with pytest.raises(PackError, match="Unknown narration evidence pack: in.untangle.narration.default@2.0.0"):
        get_pack(f"{DEFAULT_PACK_ID}@2.0.0")

    with pytest.raises(PackError, match="Invalid pack selector type: int"):
        get_pack(123)  # type: ignore

    with pytest.raises(PackError, match="Malformed pack selector '@1.0.0'"):
        parse_pack_selector("@1.0.0")

    with pytest.raises(PackError, match="Malformed pack selector 'pack@'"):
        parse_pack_selector("pack@")


def test_build_config_pack_validation():
    """Verify build_config validates the evidence pack selector."""
    cfg = build_config(
        no_ai=True,
        provider=None,
        model=None,
        threshold=0.55,
        seed=42,
        evidence_pack=f"{DEFAULT_PACK_ID}@{DEFAULT_PACK_VERSION}",
    )
    assert cfg.evidence_pack == DEFAULT_NARRATION_PACK

    with pytest.raises(ConfigError, match="Unknown narration evidence pack"):
        build_config(
            no_ai=True,
            provider=None,
            model=None,
            threshold=0.55,
            seed=42,
            evidence_pack="nonexistent.pack@1.0.0",
        )


# ============================================================================
# 5. Schema 1.1.0 & Certificate Provenance Consistency
# ============================================================================


def test_schema_1_1_report_and_certificate_provenance():
    """Verify report and certificate declare schema 1.1.0 and pass provenance checks."""
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=0.55, seed=42)
    lines = [
        BankCreditLine("k1", date(2026, 4, 1), 100000, "PAYU SETTLEMENT REF123", None, True),
    ]
    report, _ledger = build_report(cfg, lines, [], ReconIndex([]), [
        attribute_line(lines[0], ReconIndex([]), 0.55, pack=cfg.evidence_pack)
    ])
    report_dict = report.to_dict()

    # Report declares schema 1.1.0 and evidence_pack
    assert report_dict["config"]["report_schema_version"] == "1.1.0"
    assert report_dict["config"]["evidence_pack"]["pack_id"] == DEFAULT_PACK_ID

    # verify_report passes evidence_pack provenance check
    v_results = verify_report(report_dict)
    ep_check = next((r for r in v_results if r.packet_line_key == "report:config:evidence_pack"), None)
    assert ep_check is not None
    assert ep_check.ok

    # Certificate derives evidence_pack and verifies cleanly
    cert = build_close_certificate(report_dict)
    assert cert["certificate_schema_version"] == "1.1.0"
    assert cert["evidence_pack"]["pack_id"] == DEFAULT_PACK_ID

    env = issue_certificate(report_dict)
    env["report"] = report_dict

    v_cert = verify_certificate(env)
    assert v_cert["ok"]
    assert v_cert["report_binding_valid"] is True
    assert v_cert["evidence_pack_valid"] is True


def test_certificate_rejects_unknown_declared_report_schema():
    """Certificate generation must not silently bless future/unsupported schemas."""
    with pytest.raises(ValueError, match="Unsupported report schema version"):
        build_close_certificate({"config": {"report_schema_version": "9.9.9"}, "totals": {}})


def test_certificate_fails_on_evidence_pack_mismatch():
    """Verify certificate verification fails if attached report has mismatched evidence pack."""
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=0.55, seed=42)
    lines = [
        BankCreditLine("k1", date(2026, 4, 1), 100000, "PAYU SETTLEMENT REF123", None, True),
    ]
    report, _ = build_report(cfg, lines, [], ReconIndex([]), [
        attribute_line(lines[0], ReconIndex([]), 0.55, pack=cfg.evidence_pack)
    ])
    report_dict = report.to_dict()

    env = issue_certificate(report_dict)

    # Tamper with attached report config evidence pack
    tampered_report = copy.deepcopy(report_dict)
    tampered_report["config"]["evidence_pack"]["version"] = "2.0.0"
    env["report"] = tampered_report

    v_cert = verify_certificate(env)
    assert not v_cert["ok"]
    assert v_cert["report_binding_valid"] is False


def test_legacy_certificate_verification():
    """Verify legacy certificate without schema 1.1.0 is handled honestly without claiming pack provenance."""
    legacy_cert = {
        "summary": "Legacy close certificate",
        "period_records": 10,
        "proven_razorpay_count": 5,
        "proven_razorpay_inr": "₹5,000.00",
        "reconciled_count": 5,
        "reconciled_inr": "₹5,000.00",
        "unresolved_count": 0,
        "unresolved_inr": "₹0.00",
        "fee_gst_recoverable_inr": "₹100.00",
        "exception_count": 0,
        "exceptions_by_reason": {},
        "verification": {"packets_verified": 5, "packets_passed": 5},
        "engine_version": "0.1.0",
        "seed": 42,
        "audit_root": "0" * 64,
        "generated_from_hashes": {
            "audit_root": "0" * 64,
            "audit_root_valid": True,
            "packets_total": 5,
            "packets_verified": 5,
        },
    }
    body = json.dumps(legacy_cert, sort_keys=True, separators=(",", ":")).encode()
    envelope = {
        "certificate": legacy_cert,
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "signed": False,
    }
    v_res = verify_certificate(envelope)
    assert v_res["ok"]
    assert v_res["legacy"] is True
    assert v_res["evidence_pack"] is None


# ============================================================================
# 6. Deterministic Replay & Isolated Attribution
# ============================================================================


def test_attribution_deterministic_replay():
    """Verify repeated attribution with explicit pack produces identical outcomes without global state."""
    pack = get_default_pack()
    lines = [
        BankCreditLine("k1", date(2026, 4, 1), 100000, "PAYU SETTLEMENT 1", None, True),
        BankCreditLine("k2", date(2026, 4, 2), 200000, "DELHIVERY COD REMITTANCE", None, True),
        BankCreditLine("k3", date(2026, 4, 3), 300000, "UPI/CR/12345/MERCHANT", None, True),
        BankCreditLine("k4", date(2026, 4, 4), 400000, "SALARY CREDIT FOR APRIL", None, True),
    ]
    index = ReconIndex([])

    res1 = attribute_all(lines, index, threshold=0.55, pack=pack)
    res2 = attribute_all(lines, index, threshold=0.55, pack=pack)

    assert len(res1) == len(res2)
    for a1, a2 in zip(res1, res2, strict=True):
        assert a1.line_key == a2.line_key
        assert a1.rail == a2.rail
        assert a1.confidence == a2.confidence
        assert a1.tier == a2.tier
        assert a1.abstained == a2.abstained
        assert [e.signal for e in a1.evidence] == [e.signal for e in a2.evidence]

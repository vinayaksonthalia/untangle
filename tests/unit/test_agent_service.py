"""Tests for Untany Advisory Agent Evidence Service and query resolution."""

from __future__ import annotations

import pytest

from webapp.agent_service import (
    ADVISORY_NOTICE,
    AgentEvidenceSnapshot,
    resolve_agent_query,
)


@pytest.fixture
def mock_snapshot() -> AgentEvidenceSnapshot:
    return AgentEvidenceSnapshot(
        run_id="run_test_snapshot_001",
        status="completed",
        reporting_period_start="2026-04-01",
        reporting_period_end="2026-04-30",
        reconciliation_hash="f" * 64,
        engine_version="1.0.0",
        rule_pack_id="standard_rules",
        bank_adapter_id="hdfc_standard",
        summary={
            "n_bank_lines": 100,
            "total_credit_paise": 1000000,
            "reconciled_count": 95,
            "reconciled_paise": 950000,
            "unresolved_count": 5,
            "unresolved_paise": 50000,
            "fee_gst_recoverable_paise": 12500,
            "exception_count": 5,
        },
        rails=[
            {
                "rail": "razorpay_settlement",
                "label": "Razorpay Settlement",
                "amount_paise": 800000,
                "count": 80,
            },
            {"rail": "direct_upi", "label": "Direct UPI", "amount_paise": 200000, "count": 20},
        ],
        root_causes=[
            {
                "line_key": "line_1",
                "root_cause": "mdr_fee_drift",
                "resolved": True,
                "variance_paise": 1000,
                "confidence": 0.95,
            },
            {
                "line_key": "line_2",
                "root_cause": "unexplained",
                "resolved": False,
                "variance_paise": 5000,
                "confidence": 0.0,
            },
        ],
        certificate={
            "certificate_id": "cert_test_001",
            "is_signed": True,
            "content_sha256": "a" * 64,
            "report_sha256": "b" * 64,
        },
    )


def test_agent_refuses_mutating_financial_intents(mock_snapshot: AgentEvidenceSnapshot) -> None:
    mutating_prompts = [
        "Please approve journal and post to Tally",
        "Can you certify close for this period?",
        "Transfer money to the merchant bank account",
        "Override reconciliation for line_1 to mark it resolved",
        "Delete run run_test_snapshot_001 from database",
    ]

    for prompt in mutating_prompts:
        res = resolve_agent_query(mock_snapshot, prompt)
        assert res["status"] == "refused", f"Failed to refuse: {prompt}"
        assert res["intent"] == "mutating_financial_action"
        assert res["refusal_reason"] is not None
        assert "read-only" in res["refusal_reason"].lower()
        assert res["advisory_notice"] == ADVISORY_NOTICE


def test_agent_answers_totals_and_summary(mock_snapshot: AgentEvidenceSnapshot) -> None:
    res = resolve_agent_query(
        mock_snapshot, "What is the total reconciled amount and unresolved balance?"
    )
    assert res["status"] == "answered"
    assert res["intent"] == "reconciliation_summary"
    assert "950,000" in res["answer"] or "950000" in res["answer"]
    assert res["evidence"]["reconciled_paise"] == 950000
    assert res["evidence"]["unresolved_paise"] == 50000


def test_agent_answers_recoverable_fees(mock_snapshot: AgentEvidenceSnapshot) -> None:
    res = resolve_agent_query(
        mock_snapshot, "How much recoverable fee and GST drift was identified?"
    )
    assert res["status"] == "answered"
    assert res["intent"] == "fee_recoverable_inquiry"
    assert "12,500" in res["answer"] or "12500" in res["answer"]
    assert res["evidence"]["fee_gst_recoverable_paise"] == 12500


def test_agent_answers_root_causes(mock_snapshot: AgentEvidenceSnapshot) -> None:
    res = resolve_agent_query(
        mock_snapshot, "What are the root causes and variance investigations?"
    )
    assert res["status"] == "answered"
    assert res["intent"] == "investigations_breakdown"
    assert "2 investigation cases" in res["answer"]
    assert res["evidence"]["resolved_cases"] == 1
    assert res["evidence"]["abstained_cases"] == 1


def test_agent_answers_certificate_status(mock_snapshot: AgentEvidenceSnapshot) -> None:
    res = resolve_agent_query(mock_snapshot, "Is the period close certificate signed and issued?")
    assert res["status"] == "answered"
    assert res["intent"] == "certificate_inquiry"
    assert "cert_test_001" in res["answer"]
    assert res["evidence"]["is_signed"] is True


def test_agent_answers_rails_distribution(mock_snapshot: AgentEvidenceSnapshot) -> None:
    res = resolve_agent_query(mock_snapshot, "Show me the payment rails breakdown and UPI share")
    assert res["status"] == "answered"
    assert res["intent"] == "rails_breakdown"
    assert "Razorpay Settlement" in res["answer"]
    assert "Direct UPI" in res["answer"]


def test_agent_abstains_on_unsupported_queries(mock_snapshot: AgentEvidenceSnapshot) -> None:
    unsupported_prompts = [
        "What will the stock market do tomorrow?",
        "Write me a poem about reconciliation",
        "How is the weather in Mumbai?",
    ]
    for prompt in unsupported_prompts:
        res = resolve_agent_query(mock_snapshot, prompt)
        assert res["status"] == "abstained"
        assert res["intent"] == "unsupported_or_ambiguous"
        assert (
            "insufficient evidence" in res["answer"].lower()
            or "unsupported" in res["answer"].lower()
        )

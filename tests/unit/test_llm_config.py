"""Unit tests for the LLM edge: PII masking, no-op/mock client, config exit codes,
and that the narration tier only *proposes* (rules confirm)."""

from __future__ import annotations

from datetime import date

import pytest

from engine.config import ConfigError, build_config
from engine.evidence import ReconIndex
from engine.llm.client import LLMClient, LLMResponse
from engine.llm.mask import mask_text
from engine.llm.narrate import resolve_unknowns
from engine.models import BankCreditLine, Rail, RailAttribution, Tier


def test_mask_hides_pii():
    masked = mask_text("IMPS/3943044707/FROM RAJESH KUMAR/PERSONAL user@example.com 9876543210")
    assert "RAJESH KUMAR" not in masked
    assert "user@example.com" not in masked
    assert "9876543210" not in masked
    assert "<NAME_1>" in masked and "<EMAIL_1>" in masked and "<PHONE_1>" in masked


def test_mask_vpa_keeps_psp_suffix():
    masked = mask_text("UPI/CR/RZP435822307/razorpayx@ybl/COLLECT")
    assert "razorpayx@ybl" not in masked
    assert "@ybl" in masked  # structure preserved for the model


def test_client_disabled_is_noop():
    c = LLMClient(enabled=False)
    assert c.complete("sys", "user") is None


def test_config_exit3_when_ai_requested_without_key(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=groq\n", encoding="utf-8")  # no GROQ_API_KEY
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        build_config(no_ai=False, provider="groq", model="m", threshold=None,
                     seed=42, dotenv_path=str(env))


def test_config_no_ai_needs_no_key(tmp_path):
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=None,
                       seed=42, dotenv_path=str(tmp_path / "missing.env"))
    assert cfg.use_ai is False and cfg.provider_or_none() == "none"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.1, 1.5])
def test_config_rejects_nonfinite_or_out_of_range_threshold(tmp_path, bad):
    # A NaN/inf/out-of-range threshold would silently defeat the abstention safety gate
    # (confidence < NaN is always False), so build_config must reject it (Qodo full-tree #1).
    with pytest.raises(ConfigError):
        build_config(no_ai=True, provider=None, model=None, threshold=bad,
                     seed=42, dotenv_path=str(tmp_path / "missing.env"))


@pytest.mark.parametrize("ok", [0.0, 0.55, 1.0])
def test_config_accepts_valid_threshold(tmp_path, ok):
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=ok,
                       seed=42, dotenv_path=str(tmp_path / "missing.env"))
    assert cfg.threshold == ok


class _MockClient(LLMClient):
    """Enabled client that returns a canned proposal without any network call."""

    def __init__(self, reply: str):
        super().__init__(enabled=True, provider="groq", model="m", api_key="k")
        self._reply = reply

    def complete(self, system, user):
        # Assert the text handed to the model is PII-masked.
        assert "RAJESH KUMAR" not in user
        return LLMResponse(text=self._reply)


def _unknown_line(narr):
    return BankCreditLine("k1", date(2026, 6, 10), 100000, narr, None, True)


def test_narrate_rules_reject_unsupported_razorpay_claim():
    line = _unknown_line("IMPS/3943044707/FROM RAJESH KUMAR/PERSONAL")
    attrs = [RailAttribution("k1", Rail.UNKNOWN.value, 0.0, Tier.NONE.value, [], abstained=True)]
    # LLM tries to claim razorpay, but there is no Razorpay signal -> rules reject.
    out = resolve_unknowns(attrs, {"k1": line}, ReconIndex([]),
                           _MockClient("razorpay_settlement"))
    assert out[0].rail == Rail.UNKNOWN.value
    assert out[0].llm_used is True


def test_narrate_accepts_confirmable_proposal():
    line = _unknown_line("SOME AMBIGUOUS UPI CREDIT")
    attrs = [RailAttribution("k1", Rail.UNKNOWN.value, 0.0, Tier.NONE.value, [], abstained=True)]
    out = resolve_unknowns(attrs, {"k1": line}, ReconIndex([]), _MockClient("direct_upi"))
    assert out[0].rail == "direct_upi"
    assert out[0].tier == Tier.LLM.value and out[0].llm_used is True


def test_narrate_never_resolves_a_rule_conflict():
    """A rule_conflict abstention is FINAL: the LLM tier must never turn it into a rail,
    even when the narration would otherwise confirm a proposal."""
    from engine.models import EvidenceItem
    line = _unknown_line("SOME AMBIGUOUS UPI CREDIT")  # would confirm direct_upi if allowed
    conflict = RailAttribution(
        "k1", Rail.UNKNOWN.value, 0.0, Tier.NONE.value,
        [EvidenceItem("rule_conflict", "conflicting approved rules target ['direct_upi', 'unrelated']", 0.0)],
        abstained=True,
    )
    out = resolve_unknowns([conflict], {"k1": line}, ReconIndex([]), _MockClient("direct_upi"))
    assert out[0].rail == Rail.UNKNOWN.value, "conflict must stay abstained through the LLM tier"
    assert out[0].abstained is True
    assert out[0].llm_used is False, "conflict line must never be sent to the LLM"

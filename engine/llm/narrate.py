"""Residual-narration resolution — the ONLY place a language model touches attribution
(constitution II, spec FR-005/FR-011).

Rules of engagement:
- Runs ONLY on residual UNKNOWN lines that carry free-text narration.
- Text is PII-masked (``mask.py``) before it ever leaves the process.
- The model only *proposes* a rail. A razorpay_settlement (money-affecting) proposal is
  accepted ONLY when a substantive deterministic tie corroborates it (UTR / set-sum /
  Razorpay identity token, and no decoy) — never on amount agreement alone, never on the
  model's say-so. Non-money rails may be LLM-labelled on otherwise-UNKNOWN lines; they are
  recorded as llm-derived and excluded from the reconciliation and fee-GST path.
- With ``--no-ai`` the client is a no-op returning None, so every UNKNOWN stays UNKNOWN
  and the whole pipeline is byte-identical.
"""

from __future__ import annotations

from engine.evidence import ReconIndex, has_decoy_marker, razorpay_signals
from engine.llm.client import LLMClient
from engine.llm.mask import Masker
from engine.models import BankCreditLine, Rail, RailAttribution, Tier

_VALID_RAILS = {r.value for r in Rail if r != Rail.UNKNOWN}

_SYSTEM = (
    "You classify a single masked Indian bank-statement credit narration into exactly "
    "one payment rail. Reply with ONLY one of: razorpay_settlement, other_gateway, "
    "direct_upi, cod_remittance, unrelated. No explanation."
)


def _parse_rail(text: str) -> str | None:
    t = (text or "").strip().lower()
    for rail in _VALID_RAILS:
        if rail in t:
            return rail
    return None


def _confirms(proposal: str, line: BankCreditLine, index: ReconIndex) -> bool:
    """Deterministic guard: accept the LLM proposal only if evidence does not contradict it.

    A razorpay proposal requires at least a soft Razorpay signal AND no decoy marker.
    Any non-razorpay proposal is accepted (these rails are lower-risk than a false
    'this is Razorpay's'), since the LLM only ever runs on lines the deterministic
    tiers already left as UNKNOWN.
    """
    if proposal == Rail.RAZORPAY_SETTLEMENT.value:
        # Money-affecting: require a SUBSTANTIVE deterministic tie (not amount-only) and
        # no decoy. The LLM can never, alone, turn UNKNOWN into a Razorpay verdict.
        if has_decoy_marker(line):
            return False
        sig = {e.signal for e in razorpay_signals(line, index)}
        return bool(sig - {"amount_corr", "value_date_proximity"})
    # Non-money rails never enter the money path; an LLM label here is recorded and safe.
    return proposal in _VALID_RAILS


def resolve_unknowns(
    attributions: list[RailAttribution],
    lines_by_key: dict[str, BankCreditLine],
    index: ReconIndex,
    client: LLMClient,
    *,
    confidence: float = 0.6,
) -> list[RailAttribution]:
    """Return a new attribution list with residual UNKNOWNs resolved where possible.

    Deterministic and order-stable. When ``client`` is disabled this is an identity
    transform (every call returns None), preserving byte-identical output.
    """
    if not client.enabled:
        return attributions
    masker = Masker()
    out: list[RailAttribution] = []
    for attr in attributions:
        if attr.rail != Rail.UNKNOWN.value:
            out.append(attr)
            continue
        # A rule conflict (contradictory human approvals) is a MANDATORY, final abstention:
        # the edge LLM tier must never turn it back into an attributed rail. It stays UNKNOWN.
        if any(e.signal == "rule_conflict" for e in attr.evidence):
            out.append(attr)
            continue
        line = lines_by_key.get(attr.line_key)
        if line is None or not line.narration:
            out.append(attr)
            continue
        masked = masker.mask(line.raw_text())
        resp = client.complete(_SYSTEM, masked)
        if resp is None:
            out.append(RailAttribution(**{**attr.__dict__, "llm_used": True}))
            continue
        proposal = _parse_rail(resp.text)
        if proposal and _confirms(proposal, line, index):
            from engine.models import EvidenceItem  # local import keeps module import light
            ev = list(attr.evidence) + [
                EvidenceItem("llm_narration", f"LLM proposed {proposal}, rules confirmed", 0.3)
            ]
            out.append(
                RailAttribution(
                    attr.line_key, proposal, confidence, Tier.LLM.value, ev, llm_used=True
                )
            )
        else:
            out.append(RailAttribution(**{**attr.__dict__, "llm_used": True}))
    return out

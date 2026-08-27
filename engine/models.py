"""Serializable data records for the untangle engine (data-model.md).

All money is integer paise. All records are plain dataclasses so a RunReport
serializes deterministically to JSON. No record ever carries a ground-truth label.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Rail(StrEnum):
    RAZORPAY_SETTLEMENT = "razorpay_settlement"
    OTHER_GATEWAY = "other_gateway"
    DIRECT_UPI = "direct_upi"
    COD_REMITTANCE = "cod_remittance"
    UNRELATED = "unrelated"
    UNKNOWN = "UNKNOWN"          # explicit abstention (FR-003, G1)


class Tier(StrEnum):
    A = "A"          # exact evidence (clean UTR)
    B = "B"          # scored weak-evidence combination
    C = "C"          # bounded set-sum for split/merge/carry-forward
    LLM = "LLM"      # residual narration resolved with LLM assistance
    RULE = "rule_derived"  # human-approved versioned rule (G5/FR-009)
    NONE = "none"    # abstained / no tier decided


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BankCreditLine:
    """One line on the merchant's bank statement (credit or, rarely, a charge debit).

    ``key`` is a stable content hash and is NEVER the generator's line_id.
    """

    key: str
    value_date: date
    amount_paise: int          # signed net movement: +credit, -debit
    narration: str
    bank_ref: str | None
    is_credit: bool            # True when the credit column is populated

    def raw_text(self) -> str:
        return f"{self.narration} {self.bank_ref or ''}".strip()


@dataclass(frozen=True)
class ReconRow:
    """One settled Razorpay transaction. Join key is (type, entity_id)."""

    entity_id: str
    type: str                  # payment | refund | transfer | adjustment
    amount_paise: int
    fee_paise: int
    tax_paise: int             # GST-on-fee, already inside fee_paise
    debit_paise: int
    credit_paise: int
    settlement_id: str | None
    settlement_utr: str | None
    settled_at: datetime | None
    created_at: datetime | None
    on_hold: bool
    dispute_id: str | None
    order_id: str | None
    method: str | None
    description: str | None

    @property
    def net_paise(self) -> int:
        return self.credit_paise - self.debit_paise


@dataclass(frozen=True)
class OrderLedgerEntry:
    order_id: str | None
    amount_paise: int
    status: str
    created_at: datetime | None


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    signal: str
    detail: str
    weight: float


@dataclass
class RailAttribution:
    line_key: str
    rail: str
    confidence: float
    tier: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    abstained: bool = False
    llm_used: bool = False
    # Feature 004 — adversarial challenger. Set on accepted Razorpay lines (the audited margin) and on
    # margin-driven abstentions (the strongest competing explanation). None everywhere else.
    proof_margin: float | None = None
    competing_explanation: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "line_key": self.line_key,
            "rail": self.rail,
            "confidence": round(self.confidence, 4),
            "tier": self.tier,
            "abstained": self.abstained,
            "llm_used": self.llm_used,
            "evidence": [asdict(e) for e in self.evidence],
        }
        # Feature 004 — carry the challenger audit trail when present (accepted margin / abstention).
        if self.proof_margin is not None:
            d["proof_margin"] = round(self.proof_margin, 4)
        if self.competing_explanation is not None:
            d["competing_explanation"] = self.competing_explanation
        return d


@dataclass
class ReconciliationResult:
    line_key: str
    covered_entity_ids: list[tuple[str, str]]   # (type, entity_id)
    covered_net_paise: int
    credit_amount_paise: int
    residual_paise: int
    balanced: bool

    def to_dict(self) -> dict:
        return {
            "line_key": self.line_key,
            "covered_entity_ids": [list(t) for t in self.covered_entity_ids],
            "covered_net_paise": self.covered_net_paise,
            "credit_amount_paise": self.credit_amount_paise,
            "residual_paise": self.residual_paise,
            "balanced": self.balanced,
        }


@dataclass
class FeeGstRecovery:
    total_recoverable_paise: int
    by_entity: list[tuple[str, int]]

    def to_dict(self) -> dict:
        return {
            "total_recoverable_paise": self.total_recoverable_paise,
            "by_entity": [list(t) for t in self.by_entity],
        }


@dataclass
class ExceptionRecord:
    line_key: str
    reason_code: str
    detail: str
    suggested_action: str
    evidence: list[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunReport:
    totals: dict
    attributions: list[RailAttribution]
    reconciliations: list[ReconciliationResult]
    fee_gst: FeeGstRecovery | None
    exceptions: list[ExceptionRecord]
    audit_root: str
    config: dict
    proof_packets: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "totals": self.totals,
            "attributions": [a.to_dict() for a in self.attributions],
            "reconciliations": [r.to_dict() for r in self.reconciliations],
            "fee_gst": self.fee_gst.to_dict() if self.fee_gst else None,
            "exceptions": [e.to_dict() for e in self.exceptions],
            "audit_root": self.audit_root,
            "config": self.config,
            "proof_packets": self.proof_packets,
        }

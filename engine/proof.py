"""Proof Packets (US-facing evidence bundle).

For every credit the engine proved to be Razorpay's, a Proof Packet is the *receipt*: the bank
line, the verdict and its tier, the exact evidence that tied it back to the settlement report, the
settlement rows it covers, the recoverable fee-GST, and why no other rail won. It turns "trust the
precision metric" into "here is the independently-checkable proof for this rupee".

Deterministic and derived only from engine outputs — no ground truth, no raw storage beyond what the
report already contains. Serializes to JSON and flattens to CSV for a finance team / CA.
"""

from __future__ import annotations

from engine.models import (
    BankCreditLine,
    FeeGstRecovery,
    RailAttribution,
    ReconciliationResult,
    ReconRow,
    Tier,
)

# Signals that constitute a genuine, report-backed tie (the "why it's Razorpay" line).
_TIE_LABEL = {
    "utr_exact": "exact UTR match to a settlement_utr",
    "utr_suffix": "corroborated UTR suffix of a settlement_utr",
    "setsum": "bounded set-sum of settlement nets",
    "amount_corr": "amount equals a unique settlement net",
    "split_reconstruction": "provably-unique split reconstruction (legs sum to a settlement net)",
}
_TIER_LABEL = {
    Tier.A.value: "Tier A — decisive identifier tie",
    Tier.B.value: "Tier B — scored evidence combination",
    Tier.C.value: "Tier C — bounded set-sum / split reconstruction",
    Tier.LLM.value: "Tier LLM — narration resolved with edge assistance",
    Tier.RULE.value: "human-approved rule",
}


def _inr(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def build_proof_packets(
    lines: list[BankCreditLine],
    attributions: list[RailAttribution],
    reconciliations: list[ReconciliationResult],
    recon_rows: list[ReconRow],
    feegst: FeeGstRecovery,
) -> list[dict]:
    """One Proof Packet per credit proven to be Razorpay's (never an abstained credit)."""
    lines_by_key = {ln.key: ln for ln in lines}
    recon_by_key = {r.line_key: r for r in reconciliations}
    tax_by_entity = {eid: tax for eid, tax in feegst.by_entity}
    rows_by_entity = {(r.type, r.entity_id): r for r in recon_rows}

    packets: list[dict] = []
    for a in attributions:
        if a.rail != "razorpay_settlement" or a.abstained:
            continue
        line = lines_by_key.get(a.line_key)
        if line is None:
            continue

        # The decisive tie(s): the report-backed signals that made this Razorpay's.
        ties = [
            {"signal": e.signal, "detail": e.detail, "explains": _TIE_LABEL[e.signal]}
            for e in a.evidence if e.signal in _TIE_LABEL
        ]
        corroboration = [
            {"signal": e.signal, "detail": e.detail, "weight": round(e.weight, 3)}
            for e in a.evidence if e.signal not in _TIE_LABEL
        ]

        rec = recon_by_key.get(a.line_key)
        settlement = None
        fee_gst_paise = 0
        if rec is not None:
            covered = [{"type": t, "entity_id": eid} for t, eid in rec.covered_entity_ids]
            fee_gst_paise = sum(
                tax_by_entity.get(eid, 0) for _, eid in rec.covered_entity_ids
            )
            settlement = {
                "covered_entities": covered,
                "covered_net_inr": _inr(rec.covered_net_paise),
                "residual_paise": rec.residual_paise,
                "balanced": rec.balanced,
            }

        packets.append({
            "line_key": a.line_key,
            "value_date": line.value_date.isoformat(),
            "amount_inr": _inr(line.amount_paise),
            "narration": line.narration,
            "bank_ref": line.bank_ref or "",
            "verdict": {
                "rail": a.rail,
                "tier": a.tier,
                "tier_label": _TIER_LABEL.get(a.tier, a.tier),
                "confidence": round(a.confidence, 3),
            },
            "proof": {
                "ties": ties,
                "corroboration": corroboration,
                # Razorpay only wins with a report tie AND no distinctive competing rail keyword —
                # so the absence of a competing tie is itself part of the proof.
                "rejected_alternatives": (
                    "No distinctive competing rail keyword was present; the Razorpay verdict rests "
                    "on the report-backed tie(s) above, not on resemblance."
                ),
            },
            "settlement": settlement,
            "fee_gst_recoverable_inr": _inr(fee_gst_paise),
            "reconciled": rec is not None,
        })
    return packets


_CSV_COLUMNS = [
    "line_key", "value_date", "amount_inr", "narration", "bank_ref",
    "rail", "tier", "confidence", "tie_signals", "reconciled",
    "covered_entity_count", "residual_paise", "balanced", "fee_gst_recoverable_inr",
]


def _csv_field(value: str) -> str:
    s = str(value)
    if any(c in s for c in [",", '"', "\n", "\r"]):
        return '"' + s.replace('"', '""') + '"'
    return s


def proof_packets_to_csv(packets: list[dict]) -> str:
    """Flatten packets to CSV (RFC-4180 quoting) for a finance team / CA."""
    out = [",".join(_CSV_COLUMNS)]
    for p in packets:
        st = p.get("settlement") or {}
        row = [
            p["line_key"], p["value_date"], p["amount_inr"], p["narration"], p["bank_ref"],
            p["verdict"]["rail"], p["verdict"]["tier"], p["verdict"]["confidence"],
            "; ".join(t["signal"] for t in p["proof"]["ties"]),
            p["reconciled"],
            len(st.get("covered_entities", [])),
            st.get("residual_paise", ""),
            st.get("balanced", ""),
            p["fee_gst_recoverable_inr"],
        ]
        out.append(",".join(_csv_field(v) for v in row))
    return "\n".join(out) + "\n"

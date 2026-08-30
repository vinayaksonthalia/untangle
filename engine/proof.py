"""Proof Packets (US-facing evidence bundle).

For every credit the engine proved to be Razorpay's, a Proof Packet is the *receipt*: the bank
line, the verdict and its tier, the exact evidence that tied it back to the settlement report, the
settlement rows it covers, the recoverable fee-GST, and why no other rail won. It turns "trust the
precision metric" into "here is the independently-checkable proof for this rupee".

Deterministic and derived only from engine outputs — no ground truth, no raw storage beyond what the
report already contains. Serializes to JSON and flattens to CSV for a finance team / CA.
"""

from __future__ import annotations

from typing import Any

from engine.covered import resolve_covered_rows_by_id
from engine.evidence import narration_rail_signals
from engine.models import (
    BankCreditLine,
    FeeGstRecovery,
    RailAttribution,
    ReconciliationResult,
    ReconRow,
    Tier,
)

_PENDING_GST = "pending"

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
    *,
    rejected_matches: list[dict] | None = None,
) -> list[dict]:
    """One Proof Packet per credit proven to be Razorpay's (never an abstained credit)."""
    lines_by_key = {ln.key: ln for ln in lines}
    recon_by_key = {r.line_key: r for r in reconciliations}
    # Key tax by the FULL (type, entity_id) join — the same composite key reconciliation and
    # fee_gst use — so two entities of different types sharing an id can't collide (Qodo #3).
    tax_by_entity = {(r.type, r.entity_id): r.tax_paise for r in recon_rows}
    row_by_id = {f"recon_{i}": r for i, r in enumerate(recon_rows)}
    # Multimap for the legacy (pre-row-id) fallback: occurrence-consuming so duplicate covered keys
    # still resolve to distinct REAL rows (a bare tax map yields ints, losing settlement ids).
    from collections import defaultdict

    rows_by_key: dict[tuple[str, str], list[ReconRow]] = defaultdict(list)
    for _r in recon_rows:
        rows_by_key[(_r.type, _r.entity_id)].append(_r)

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
        # Invariant (post proof-gate): a proven Razorpay verdict always rests on a report-backed
        # tie. A packet with no tie has nothing to prove, so it is not a Proof Packet — skip it
        # rather than present resemblance as proof.
        if not ties:
            continue
        corroboration = [
            {"signal": e.signal, "detail": e.detail, "weight": round(e.weight, 3)}
            for e in a.evidence if e.signal not in _TIE_LABEL
        ]

        # Accurate "why not another rail" — derived from the line's ACTUAL competing signals, not
        # asserted. A hard tie (e.g. exact UTR) outranks a narration keyword, so a competing keyword
        # may be present; say so honestly rather than claim none existed (Qodo #2).
        competing = [rail.value for rail in narration_rail_signals(line)]
        if competing:
            rejected = (
                f"A distinctive narration keyword for {', '.join(sorted(competing))} was also present, "
                "but the report-backed tie(s) above outrank narration resemblance and decide the verdict."
            )
        else:
            rejected = (
                "No distinctive competing rail keyword was present; the Razorpay verdict rests on the "
                "report-backed tie(s) above, not on resemblance."
            )

        rec = recon_by_key.get(a.line_key)
        settlement = None
        claimed_sids: set[str] = set()
        if rec is not None:
            covered = []
            for i, (t, eid) in enumerate(rec.covered_entity_ids):
                item = {"type": t, "entity_id": eid}
                if rec.covered_row_ids and i < len(rec.covered_row_ids):
                    item["row_id"] = rec.covered_row_ids[i]
                covered.append(item)
            if rec.covered_row_ids:
                # Strict path: exact, validated rows (fail-closed on identity/duplicate mismatch).
                covered_rows = resolve_covered_rows_by_id(rec, row_by_id)
                fee_gst_paise = sum(r.tax_paise for r in covered_rows)
                rows_for_sids = covered_rows
            else:
                # Legacy fallback (pre-row-id data): fee-GST from the lossy (type, entity_id) tax
                # map (byte-identical with prior behaviour), but settlement ids from occurrence-
                # consuming REAL rows — a bare tax map yields ints, so ids were previously lost.
                fee_gst_paise = sum(tax_by_entity.get((t, eid), 0) for t, eid in rec.covered_entity_ids)
                _seen: dict[tuple[str, str], int] = defaultdict(int)
                rows_for_sids = []
                for t, eid in rec.covered_entity_ids:
                    bucket = rows_by_key.get((t, eid), [])
                    if _seen[(t, eid)] < len(bucket):
                        rows_for_sids.append(bucket[_seen[(t, eid)]])
                    _seen[(t, eid)] += 1
            fee_gst_display = _inr(fee_gst_paise)
            for row in rows_for_sids:
                if row.settlement_id:
                    claimed_sids.add(row.settlement_id)
            settlement = {
                "covered_entities": covered,
                "covered_net_inr": _inr(rec.covered_net_paise),
                "residual_paise": rec.residual_paise,
                "balanced": rec.balanced,
            }
        else:
            # Unresolved (e.g. a reconstructed split leg): the recoverable GST is UNKNOWN until
            # entity-level reconciliation, NOT zero. Never present an unknown as ₹0.00 (Qodo #1).
            fee_gst_display = _PENDING_GST

        proof_data: dict[str, Any] = {
            "ties": ties,
            "corroboration": corroboration,
            "rejected_alternatives": rejected,
        }

        # Feature 006: Thread through violated constraints and globally-forced alternatives
        if rejected_matches is not None:
            this_credit_rejected = [
                r for r in rejected_matches if a.line_key in r.get("credit_keys", ())
            ]
            contenders_rejected = [
                r for r in rejected_matches
                if r.get("target_id") in claimed_sids and a.line_key not in r.get("credit_keys", ())
            ]
            violated_constraints = []
            for cr in this_credit_rejected:
                violated_constraints.append({
                    "type": "credit_candidate_rejected",
                    "candidate_id": cr["candidate_id"],
                    "target_id": cr["target_id"],
                    "violated_constraint": cr["violated_constraint"],
                    "detail": cr["detail"],
                })
            for cnd in contenders_rejected:
                violated_constraints.append({
                    "type": "contender_settlement_rejected",
                    "contender_credit_keys": list(cnd["credit_keys"]),
                    "target_id": cnd["target_id"],
                    "violated_constraint": cnd["violated_constraint"],
                    "detail": cnd["detail"],
                })
            proof_data["violated_constraints"] = violated_constraints

        # Evidence courtroom: the adversarial challenger's audit of THIS verdict — the proof margin
        # (how far the Razorpay score sits above the best competing explanation) and the strongest
        # explanation it rejected, including which tie signal, when removed, collapses the score.
        # Present only when the non-gating audit ran (report/UI path); absent otherwise.
        if a.proof_margin is not None:
            proof_data["challenge"] = {
                "proof_margin": round(a.proof_margin, 4),
                "rejected_explanation": a.competing_explanation,
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
            "proof": proof_data,
            "settlement": settlement,
            "fee_gst_recoverable_inr": fee_gst_display,
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
    # CSV formula-injection guard: a field beginning with = + - @ (or a tab/CR) can execute as a
    # formula when the file is opened in a spreadsheet. Neutralize by prefixing a single quote.
    if s[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        s = "'" + s
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

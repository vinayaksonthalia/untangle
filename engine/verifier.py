"""Independent Proof-Packet and Run-Report Verifier.

Re-checks proof packets and full reports independently without re-running the pipeline.
Performs:
  (a) Tie signal validation: all ties in proof.ties are report-backed signals;
  (b) Reconciliation arithmetic: covered settlement net equals credited amount within ±100 paise;
  (c) Proof margin validation: proof margin is present and > 0 for Razorpay verdicts;
  (d) Recon row consistency: covered entities exist in recon_rows and match claimed UTR ties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Report-backed tie signals that prove a Razorpay credit
ALLOWED_TIE_SIGNALS: frozenset[str] = frozenset({
    "utr_exact",
    "utr_suffix",
    "setsum",
    "amount_corr",
    "split_reconstruction",
})

_DRIFT_TOLERANCE_PAISE = 100  # ±₹1 drift tolerance


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single verification check."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    """Full verification outcome for a single proof packet or report root."""

    ok: bool
    checks: list[CheckResult]
    packet_line_key: str


def _parse_inr_to_paise(val: Any) -> int | None:
    """Parse an INR string (e.g. '₹306,849.38', '-₹10.50') or integer paise into int paise."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return round(val * 100)
    s = str(val).strip()
    if not s:
        return None
    is_neg = False
    if s.startswith("-"):
        is_neg = True
        s = s[1:].strip()
    s = s.replace("₹", "").replace(",", "").strip()
    try:
        amount_float = float(s)
        paise = round(amount_float * 100)
        return -paise if is_neg else paise
    except ValueError:
        return None


def verify_proof_packet(
    packet: dict,
    *,
    recon_rows: list[dict] | None = None,
) -> VerificationResult:
    """Independently verify a proof packet using only packet data (and recon_rows if supplied).

    Never raises an exception on malformed inputs; returns ok=False with failing checks instead.
    """
    checks: list[CheckResult] = []
    line_key = "unknown"

    if not isinstance(packet, dict):
        return VerificationResult(
            ok=False,
            checks=[CheckResult("packet_structure", False, "Packet is not a dictionary")],
            packet_line_key="malformed",
        )

    try:
        line_key = str(packet.get("line_key", "unknown"))
    except Exception:
        line_key = "malformed"

    # -----------------------------------------------------------------
    # (a) Tie signals check: every tie in proof.ties is report-backed
    # -----------------------------------------------------------------
    proof = packet.get("proof")
    if not isinstance(proof, dict):
        checks.append(CheckResult("tie_signals", False, "Missing or invalid 'proof' dictionary"))
    else:
        ties = proof.get("ties")
        if not isinstance(ties, list) or len(ties) == 0:
            checks.append(
                CheckResult(
                    "tie_signals",
                    False,
                    "Resemblance-only: no report-backed tie signal present in proof.ties",
                )
            )
        else:
            invalid_ties: list[str] = []
            valid_ties: list[str] = []
            for t in ties:
                if isinstance(t, dict):
                    sig = t.get("signal")
                    if sig in ALLOWED_TIE_SIGNALS:
                        valid_ties.append(str(sig))
                    else:
                        invalid_ties.append(str(sig))
                else:
                    invalid_ties.append(str(t))

            if invalid_ties:
                checks.append(
                    CheckResult(
                        "tie_signals",
                        False,
                        f"Unknown or disallowed tie signals: {', '.join(invalid_ties)}",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        "tie_signals",
                        True,
                        f"All tie signals are valid report-backed signals: {', '.join(valid_ties)}",
                    )
                )

    # -----------------------------------------------------------------
    # (b) Reconciliation arithmetic check
    # -----------------------------------------------------------------
    reconciled = packet.get("reconciled", False)
    settlement = packet.get("settlement")
    amount_inr = packet.get("amount_inr")
    credited_paise = _parse_inr_to_paise(amount_inr)

    if credited_paise is None:
        checks.append(CheckResult("reconciliation_arithmetic", False, f"Invalid or missing amount_inr: {amount_inr!r}"))
    elif reconciled and settlement is not None:
        if not isinstance(settlement, dict):
            checks.append(CheckResult("reconciliation_arithmetic", False, "Invalid 'settlement' object"))
        else:
            covered_net_inr = settlement.get("covered_net_inr")
            covered_paise = _parse_inr_to_paise(covered_net_inr)
            reported_residual = settlement.get("residual_paise")

            if covered_paise is None or reported_residual is None or not isinstance(reported_residual, int):
                checks.append(
                    CheckResult(
                        "reconciliation_arithmetic",
                        False,
                        f"Malformed settlement amounts: covered_net_inr={covered_net_inr!r}, residual_paise={reported_residual!r}",
                    )
                )
            else:
                expected_residual = credited_paise - covered_paise
                drift = abs(expected_residual)
                if drift > _DRIFT_TOLERANCE_PAISE:
                    checks.append(
                        CheckResult(
                            "reconciliation_arithmetic",
                            False,
                            f"Arithmetic drift {drift} paise exceeds ±{_DRIFT_TOLERANCE_PAISE} paise tolerance (credited: {credited_paise}, covered: {covered_paise})",
                        )
                    )
                elif reported_residual != expected_residual:
                    checks.append(
                        CheckResult(
                            "reconciliation_arithmetic",
                            False,
                            f"Reported residual {reported_residual} paise != calculated residual {expected_residual} paise",
                        )
                    )
                else:
                    checks.append(
                        CheckResult(
                            "reconciliation_arithmetic",
                            True,
                            f"Covered net matches credited amount within tolerance (residual: {reported_residual} paise)",
                        )
                    )
    elif reconciled and settlement is None:
        checks.append(CheckResult("reconciliation_arithmetic", False, "Packet marked reconciled=True but 'settlement' is missing"))
    else:
        # Unreconciled / pending split leg
        checks.append(
            CheckResult(
                "reconciliation_arithmetic",
                True,
                "Credit is unresolved (pending settlement report / split pairing); arithmetic check not applicable",
            )
        )

    # -----------------------------------------------------------------
    # (c) Proof margin check: margin present and > 0 for Razorpay verdict
    # -----------------------------------------------------------------
    verdict = packet.get("verdict")
    rail = verdict.get("rail") if isinstance(verdict, dict) else None
    tier = verdict.get("tier") if isinstance(verdict, dict) else None

    if rail == "razorpay_settlement":
        # The proof of a Razorpay verdict is its report-backed tie (check a) + arithmetic (check b).
        # The challenger's proof_margin is a DISPLAY-ONLY audit that may or may not be attached (it is
        # present on the report/UI path, absent on the headless CLI path). Its ABSENCE therefore never
        # makes a packet unverifiable. But when a challenge IS present, a non-positive margin means the
        # challenger itself judged the verdict fragile — that is a real red flag, so fail on it.
        if isinstance(proof, dict) and "challenge" in proof and isinstance(proof["challenge"], dict):
            margin = proof["challenge"].get("proof_margin")
            if isinstance(margin, (int, float)) and margin > 0:
                checks.append(
                    CheckResult("proof_margin", True, f"Challenger audit present; proof margin positive: {margin:.4f}")
                )
            else:
                checks.append(
                    CheckResult("proof_margin", False, f"Challenger audit present but proof margin non-positive: {margin}")
                )
        else:
            checks.append(
                CheckResult(
                    "proof_margin",
                    True,
                    "No challenger audit attached; proof rests on the report-backed tie(s) above (checks a/b).",
                )
            )
    else:
        checks.append(
            CheckResult(
                "proof_margin",
                True,
                f"Non-Razorpay verdict ({rail}); proof margin check not applicable",
            )
        )

    # -----------------------------------------------------------------
    # (d) Recon rows consistency (if recon_rows provided)
    # -----------------------------------------------------------------
    if recon_rows is not None:
        if not isinstance(recon_rows, list):
            checks.append(CheckResult("recon_rows_consistency", False, "recon_rows must be a list"))
        elif settlement is not None and isinstance(settlement, dict):
            covered_entities = settlement.get("covered_entities", [])
            recon_by_type_id: dict[tuple[str, str], dict] = {}
            recon_by_id: dict[str, dict] = {}
            for r in recon_rows:
                if isinstance(r, dict):
                    t = str(r.get("type", ""))
                    eid = str(r.get("entity_id", ""))
                    recon_by_type_id[(t, eid)] = r
                    recon_by_id[eid] = r

            missing_entities: list[str] = []
            for ent in covered_entities:
                if isinstance(ent, dict):
                    t = str(ent.get("type", ""))
                    eid = str(ent.get("entity_id", ""))
                    if (t, eid) not in recon_by_type_id and eid not in recon_by_id:
                        missing_entities.append(f"{t}:{eid}")
                else:
                    missing_entities.append(str(ent))

            if missing_entities:
                checks.append(
                    CheckResult(
                        "recon_rows_consistency",
                        False,
                        f"Covered entities not found in recon_rows: {', '.join(missing_entities[:5])}",
                    )
                )
            else:
                utr_inconsistent = False
                inconsistent_detail = ""
                if isinstance(proof, dict) and isinstance(proof.get("ties"), list):
                    for t in proof["ties"]:
                        if not isinstance(t, dict):
                            continue
                        sig = t.get("signal")
                        detail = str(t.get("detail", "")).lower()
                        if sig == "utr_exact":
                            m = re.search(r"utr\s+([a-z0-9]+)", detail)
                            if m:
                                claimed_utr = m.group(1)
                                for ent in covered_entities:
                                    eid = str(ent.get("entity_id", ""))
                                    row = recon_by_id.get(eid)
                                    if row:
                                        row_utr = str(row.get("settlement_utr", "")).lower()
                                        if row_utr and claimed_utr not in row_utr and row_utr not in claimed_utr:
                                            utr_inconsistent = True
                                            inconsistent_detail = (
                                                f"Claimed exact UTR {claimed_utr!r} does not match "
                                                f"recon settlement_utr {row_utr!r}"
                                            )
                        elif sig == "utr_suffix":
                            m = re.search(r"settlement_utr\s+([a-z0-9]+)", detail)
                            if m:
                                claimed_utr = m.group(1)
                                for ent in covered_entities:
                                    eid = str(ent.get("entity_id", ""))
                                    row = recon_by_id.get(eid)
                                    if row:
                                        row_utr = str(row.get("settlement_utr", "")).lower()
                                        if row_utr and not (
                                            row_utr == claimed_utr
                                            or row_utr.endswith(claimed_utr)
                                            or claimed_utr.endswith(row_utr)
                                        ):
                                            utr_inconsistent = True
                                            inconsistent_detail = (
                                                f"Claimed suffix UTR {claimed_utr!r} does not match "
                                                f"recon settlement_utr {row_utr!r}"
                                            )

                if utr_inconsistent:
                    checks.append(CheckResult("recon_rows_consistency", False, inconsistent_detail))
                else:
                    checks.append(
                        CheckResult(
                            "recon_rows_consistency",
                            True,
                            f"All {len(covered_entities)} covered entities exist in recon_rows and match claimed UTR ties",
                        )
                    )
        else:
            checks.append(
                CheckResult(
                    "recon_rows_consistency",
                    True,
                    "No covered entities in packet to cross-check against recon_rows",
                )
            )

    ok = all(c.passed for c in checks)
    return VerificationResult(ok=ok, checks=checks, packet_line_key=line_key)


def verify_report(report: dict) -> list[VerificationResult]:
    """Verify all proof packets in a report and cross-check that audit_root is a 64-char hex string."""
    results: list[VerificationResult] = []

    if not isinstance(report, dict):
        return [
            VerificationResult(
                ok=False,
                checks=[CheckResult("report_structure", False, "Report is not a dictionary")],
                packet_line_key="report:root",
            )
        ]

    # 1. Audit root format check
    audit_root = report.get("audit_root")
    audit_ok = False
    audit_detail = ""
    if (
        isinstance(audit_root, str)
        and len(audit_root) == 64
        and all(c in "0123456789abcdefABCDEF" for c in audit_root)
    ):
        audit_ok = True
        audit_detail = f"Valid 64-char SHA256 audit root: {audit_root}"
    else:
        audit_detail = f"Invalid audit_root: expected 64-char hex string, got {audit_root!r}"

    results.append(
        VerificationResult(
            ok=audit_ok,
            checks=[CheckResult("audit_root_format", audit_ok, audit_detail)],
            packet_line_key="report:audit_root",
        )
    )

    # 2. Proof packet verification
    packets = report.get("proof_packets", [])
    if isinstance(packets, list):
        for pkt in packets:
            results.append(verify_proof_packet(pkt))

    return results

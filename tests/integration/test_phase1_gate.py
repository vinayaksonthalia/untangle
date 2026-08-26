"""Phase 1 Acceptance Gate Test (ANTIGRAVITY_BUILD_PLAN.md §2 Phase 1).

Gate requirements:
  1. Pinned 20-row sample composition:
     - >=3 set-sum-ambiguous credits (>1 satisfying subset)
     - >=2 coincidental-amount credits (amount equals a Razorpay total, non-Razorpay narration)
     - >=2 unrelated credits
     - >=2 that MUST abstain
  2. Every one of the 20 credits is either attributed (rail + confidence + evidence)
     or abstained (reason).
  3. G1: Zero credits attributed to razorpay_settlement on coincidental amount alone.
  4. G2: Zero forced set-sum picks (a credit with >1 satisfying leg-subset MUST abstain
     with reason 'multiple_satisfying_subsets').
  5. Deterministic and reproducible with a fixed seed.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from engine.attribute import attribute_all
from engine.config import DEFAULT_THRESHOLD
from engine.evidence import ReconIndex
from engine.exceptions import build_exceptions
from engine.models import BankCreditLine, Rail, ReconRow


def _make_recon_rows() -> list[ReconRow]:
    """Build settlement records covering Tier A, unique set-sum, ambiguous set-sum, and coincidental."""
    rows: list[ReconRow] = []

    def _add(sid: str, net: int, dt: date, utr: str | None = None):
        # In Razorpay schema: credit_paise = net (for payment rows, debit = 0)
        rows.append(
            ReconRow(
                entity_id=f"pay_{sid}",
                type="payment",
                amount_paise=net + 200,
                fee_paise=200,
                tax_paise=30,
                debit_paise=0,
                credit_paise=net,
                settlement_id=sid,
                settlement_utr=utr,
                settled_at=datetime.combine(dt, datetime.min.time()),
                created_at=datetime(2026, 6, 1),
                on_hold=False,
                dispute_id=None,
                order_id=f"ord_{sid}",
                method="upi",
                description="test",
            )
        )

    # 1. Tier A settlements (with clean UTRs)
    _add("setl_a1", 150000, date(2026, 6, 10), utr="1780498800aaaaaa")
    _add("setl_a2", 250000, date(2026, 6, 11), utr="1780498800bbbbbb")
    _add("setl_a3", 350000, date(2026, 6, 12), utr="1780498800cccccc")

    # 2. Tier C unique set-sum settlements
    # Target 103,000 = setl_u1 (41,000) + setl_u2 (62,000)
    _add("setl_u1", 41000, date(2026, 6, 10))
    _add("setl_u2", 62000, date(2026, 6, 10))
    # Target 127,000 = setl_u3 (53,000) + setl_u4 (74,000)
    _add("setl_u3", 53000, date(2026, 6, 12))
    _add("setl_u4", 74000, date(2026, 6, 12))

    # 3. Set-sum ambiguous 1: Target 203,000 = (amb1_a + amb1_b) AND (amb1_c + amb1_d)
    _add("setl_amb1_a", 91000, date(2026, 6, 15))
    _add("setl_amb1_b", 112000, date(2026, 6, 15))
    _add("setl_amb1_c", 81000, date(2026, 6, 15))
    _add("setl_amb1_d", 122000, date(2026, 6, 15))

    # 4. Set-sum ambiguous 2: Target 315,000 = single (amb2_s) AND combo (amb2_x + amb2_y)
    _add("setl_amb2_s", 315000, date(2026, 6, 16))
    _add("setl_amb2_x", 145000, date(2026, 6, 16))
    _add("setl_amb2_y", 170000, date(2026, 6, 16))

    # 5. Set-sum ambiguous 3: Target 453,000 = (amb3_p + amb3_q + amb3_r) AND (amb3_s + amb3_t + amb3_u)
    _add("setl_amb3_p", 101000, date(2026, 6, 17))
    _add("setl_amb3_q", 151000, date(2026, 6, 17))
    _add("setl_amb3_r", 201000, date(2026, 6, 17))
    _add("setl_amb3_s", 51000, date(2026, 6, 17))
    _add("setl_amb3_t", 181000, date(2026, 6, 17))
    _add("setl_amb3_u", 221000, date(2026, 6, 17))

    # 6. Coincidental-amount settlements
    _add("setl_coinc1", 500000, date(2026, 6, 18), utr="1780498800dddddd")
    _add("setl_coinc2", 750000, date(2026, 6, 19), utr="1780498800eeeeee")

    return rows


def _make_pinned_20_rows() -> list[tuple[BankCreditLine, str]]:
    """Return the pinned 20 bank credit lines and their expected category label.

    Composition check:
      - 3 set-sum-ambiguous (>=3 required)
      - 2 coincidental-amount (>=2 required)
      - 3 unrelated (>=2 required)
      - 3 must-abstain (>=2 required)
    """
    lines: list[tuple[BankCreditLine, str]] = [
        # --- Group 1: Tier A Exact UTR matches (3 lines) ---
        (
            BankCreditLine("k_01", date(2026, 6, 10), 150000,
                           "IMPS/1780498800aaaaaa/Razorpay/Settlement", "1780498800aaaaaa", True),
            "tier_a_rzp",
        ),
        (
            BankCreditLine("k_02", date(2026, 6, 11), 250000,
                           "NEFT CR-RATN0000088-RAZORPAY-1780498800bbbbbb", "1780498800bbbbbb", True),
            "tier_a_rzp",
        ),
        (
            BankCreditLine("k_03", date(2026, 6, 12), 350000,
                           "RTGS/1780498800cccccc/RAZORPAY SOFTWARE", "1780498800cccccc", True),
            "tier_a_rzp",
        ),

        # --- Group 2: Tier C Unique Set-Sum (2 lines) ---
        (
            BankCreditLine("k_04", date(2026, 6, 10), 103000,
                           "NEFT CR-RATN0000088-SETTLEMENT", None, True),
            "tier_c_unique_setsum",
        ),
        (
            BankCreditLine("k_05", date(2026, 6, 12), 127000,
                           "RAZORPAY SETTLEMENT", None, True),
            "tier_c_unique_setsum",
        ),

        # --- Group 3: Set-Sum Ambiguous (3 lines) [>=3 REQUIRED] ---
        # Ambiguous 1: 2 distinct 2-leg pairs sum to 203,000
        (
            BankCreditLine("k_06", date(2026, 6, 15), 203000,
                           "NEFT CR-RATN0000088-SETTLEMENT", None, True),
            "set_sum_ambiguous",
        ),
        # Ambiguous 2: single settlement net (315k) AND 2-leg pair sum to 315,000
        (
            BankCreditLine("k_07", date(2026, 6, 16), 315000,
                           "RAZORPAY SETTLEMENT", None, True),
            "set_sum_ambiguous",
        ),
        # Ambiguous 3: 2 distinct 3-leg subsets sum to 453,000
        (
            BankCreditLine("k_08", date(2026, 6, 17), 453000,
                           "NEFT CR-RAZORPAY-MERCHANT SETTLEMENT", None, True),
            "set_sum_ambiguous",
        ),

        # --- Group 4: Coincidental Amount (2 lines) [>=2 REQUIRED] ---
        # Equals 500,000 (setl_coinc1) but non-Razorpay narration (PayU)
        (
            BankCreditLine("k_09", date(2026, 6, 18), 500000,
                           "RTGS/PAYU PAYMENTS PVT LTD/PAYU123/PAYOUT", "PAYU123", True),
            "coincidental_amount",
        ),
        # Equals 750,000 (setl_coinc2) but non-Razorpay narration (COD)
        (
            BankCreditLine("k_10", date(2026, 6, 19), 750000,
                           "NEFT-SHOPIFY COMMERCE-COD-COD999", "COD999", True),
            "coincidental_amount",
        ),

        # --- Group 5: Direct UPI Rail (2 lines) ---
        (
            BankCreditLine("k_11", date(2026, 6, 11), 32000,
                           "UPI SETTLEMENT NPCI 473815479060", None, True),
            "direct_upi",
        ),
        (
            BankCreditLine("k_12", date(2026, 6, 12), 48500,
                           "UPI/CR/482910382910/merchant@okaxis", None, True),
            "direct_upi",
        ),

        # --- Group 6: Other Gateway Rail (1 line) ---
        (
            BankCreditLine("k_13", date(2026, 6, 13), 210000,
                           "RTGS/CASHFREE PAYMENTS PVT LTD/CF9201", "CF9201", True),
            "other_gateway",
        ),

        # --- Group 7: COD Remittance Rail (1 line) ---
        (
            BankCreditLine("k_14", date(2026, 6, 14), 145000,
                           "NEFT-DELHIVERY COD-DEL39201", "DEL39201", True),
            "cod_remittance",
        ),

        # --- Group 8: Unrelated (3 lines) [>=2 REQUIRED] ---
        (
            BankCreditLine("k_15", date(2026, 6, 15), 50000,
                           "IMPS/3943044707/FROM RAJESH KUMAR/PERSONAL", None, True),
            "unrelated",
        ),
        (
            BankCreditLine("k_16", date(2026, 6, 16), 12500,
                           "SAVINGS ACCOUNT INTEREST CREDIT INT.PD", None, True),
            "unrelated",
        ),
        (
            BankCreditLine("k_17", date(2026, 6, 17), 89000,
                           "GST REFUND CBIC REF93810293", None, True),
            "unrelated",
        ),

        # --- Group 9: Must Abstain (3 lines) [>=2 REQUIRED] ---
        (
            BankCreditLine("k_18", date(2026, 6, 18), 77000,
                           "TRANSFER 928374928 UNKNOWN SOURCE", None, True),
            "must_abstain",
        ),
        (
            BankCreditLine("k_19", date(2026, 6, 19), 88000,
                           "NEFT CR-RANDOMCORP-PAYMENT 99238", None, True),
            "must_abstain",
        ),
        (
            BankCreditLine("k_20", date(2026, 6, 20), 99000,
                           "CREDIT TXN 84920492 NO DETAILS", None, True),
            "must_abstain",
        ),
    ]
    return lines


def test_phase1_pinned_sample_composition():
    """Verify that the pinned sample strictly contains the required composition."""
    sample = _make_pinned_20_rows()
    assert len(sample) == 20, f"Pinned sample must have exactly 20 rows, got {len(sample)}"

    categories = [cat for _, cat in sample]
    n_setsum_ambig = categories.count("set_sum_ambiguous")
    n_coincidental = categories.count("coincidental_amount")
    n_unrelated = categories.count("unrelated")
    n_must_abstain = categories.count("must_abstain")

    assert n_setsum_ambig >= 3, f"Must have >=3 set-sum-ambiguous, got {n_setsum_ambig}"
    assert n_coincidental >= 2, f"Must have >=2 coincidental-amount, got {n_coincidental}"
    assert n_unrelated >= 2, f"Must have >=2 unrelated, got {n_unrelated}"
    assert n_must_abstain >= 2, f"Must have >=2 must-abstain, got {n_must_abstain}"


def test_phase1_acceptance_gate_execution():
    """Run Phase 1 attribution on the pinned 20-row sample and verify ALL gate conditions."""
    recon_rows = _make_recon_rows()
    index = ReconIndex(recon_rows)
    sample = _make_pinned_20_rows()
    lines = [line for line, _ in sample]

    attributions = attribute_all(lines, index, threshold=DEFAULT_THRESHOLD)

    # Gate Condition 1: Every one of the 20 credits is either attributed or abstained.
    assert len(attributions) == 20
    for a in attributions:
        if a.abstained:
            assert a.rail == Rail.UNKNOWN.value
        else:
            assert a.rail in {
                Rail.RAZORPAY_SETTLEMENT.value,
                Rail.OTHER_GATEWAY.value,
                Rail.DIRECT_UPI.value,
                Rail.COD_REMITTANCE.value,
                Rail.UNRELATED.value,
            }
            assert a.confidence >= DEFAULT_THRESHOLD
            assert len(a.evidence) > 0

    attr_by_key = {a.line_key: a for a in attributions}

    # Gate Condition 2: G1 — No coincidental amount credit is EVER attributed to razorpay_settlement.
    coinc_keys = [line.key for line, cat in sample if cat == "coincidental_amount"]
    assert len(coinc_keys) >= 2
    for k in coinc_keys:
        a = attr_by_key[k]
        assert a.rail != Rail.RAZORPAY_SETTLEMENT.value, (
            f"Line {k} was attributed to Razorpay on coincidental amount alone (VIOLATES G1)!"
        )

    # Gate Condition 3: G2 — Every set-sum-ambiguous credit MUST ABSTAIN.
    # Zero forced set-sum picks.
    ambig_keys = [line.key for line, cat in sample if cat == "set_sum_ambiguous"]
    assert len(ambig_keys) >= 3
    for k in ambig_keys:
        a = attr_by_key[k]
        assert a.abstained is True, (
            f"Line {k} has >1 satisfying set-sum subset but was NOT abstained (VIOLATES G2)!"
        )
        assert a.rail == Rail.UNKNOWN.value
        assert any(e.signal == "multiple_satisfying_subsets" for e in a.evidence), (
            f"Line {k} did not record 'multiple_satisfying_subsets' in evidence: {a.evidence}"
        )

    # Gate Condition 4: Unrelated credits attributed to unrelated rail.
    unrelated_keys = [line.key for line, cat in sample if cat == "unrelated"]
    for k in unrelated_keys:
        a = attr_by_key[k]
        assert a.rail == Rail.UNRELATED.value
        assert not a.abstained

    # Gate Condition 5: Must-abstain credits abstain.
    abstain_keys = [line.key for line, cat in sample if cat == "must_abstain"]
    for k in abstain_keys:
        a = attr_by_key[k]
        assert a.abstained is True
        assert a.rail == Rail.UNKNOWN.value

    # Gate Condition 6: Exception generation maps multiple_satisfying_subsets properly.
    lines_by_key = {l.key: l for l in lines}
    exceptions = build_exceptions(attributions, [], lines_by_key)
    ambig_exceptions = [e for e in exceptions if e.reason_code == "multiple_satisfying_subsets"]
    assert len(ambig_exceptions) == len(ambig_keys), (
        f"Expected {len(ambig_keys)} multiple_satisfying_subsets exceptions, got {len(ambig_exceptions)}"
    )

    # Gate Condition 7: Deterministic and reproducible across re-runs.
    attr_rerun = attribute_all(lines, index, threshold=DEFAULT_THRESHOLD)
    for a1, a2 in zip(attributions, attr_rerun, strict=True):
        assert a1.to_dict() == a2.to_dict()

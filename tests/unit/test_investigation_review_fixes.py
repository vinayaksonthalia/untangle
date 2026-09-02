"""Regression tests for the PR #65 review fixes.

Covers the follow-up findings on the investigation-benchmark fixes:
  - #4 partial-capture resolves when a fully-captured row is present (mixed settlement)
  - #1 one-sided capture evidence is ambiguous -> fail closed (abstain, no voucher)
  - #3 _as_int_paise rejects booleans / non-integer floats
  - #5 voucher scoring rejects empty / zero / wrong-sized / sub-paise vouchers
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from engine.evidence import ReconIndex
from engine.ingest import InputError, _as_int_paise
from engine.investigate import (
    ROOT_CAUSE_PARTIAL_CAPTURE,
    ROOT_CAUSE_UNEXPLAINED,
    investigate,
)
from engine.models import BankCreditLine, ReconciliationResult, ReconRow
from eval.metrics import _voucher_corrects_variance


def _bank(key: str, paise: int) -> BankCreditLine:
    return BankCreditLine(
        key=key,
        value_date=date(2024, 4, 10),
        amount_paise=paise,
        narration=f"CMS/ RAZORPAY SETTLEMENT / {key} / RATN0000001",
        bank_ref="RATN0000001",
        is_credit=True,
    )


def _pay(eid: str, amount: int, authorized: int | None, captured: int | None) -> ReconRow:
    return ReconRow(
        entity_id=eid,
        type="payment",
        amount_paise=amount,
        fee_paise=0,
        tax_paise=0,
        debit_paise=0,
        credit_paise=amount,
        settlement_id="setl_mix",
        settlement_utr="UTR123456",
        settled_at=datetime(2024, 4, 10, 12, 0, 0),
        created_at=datetime(2024, 4, 9, 10, 0, 0),
        on_hold=False,
        dispute_id=None,
        order_id=f"order_{eid}",
        method="card",
        description=None,
        authorized_amount_paise=authorized,
        captured_amount_paise=captured,
    )


def _rec(line: BankCreditLine, covered_net: int) -> ReconciliationResult:
    return ReconciliationResult(
        line_key=line.key,
        covered_entity_ids=[("payment", "pay_A"), ("payment", "pay_B")],
        covered_net_paise=covered_net,
        credit_amount_paise=line.amount_paise,
        residual_paise=line.amount_paise - covered_net,
        balanced=False,
    )


def test_partial_capture_resolves_with_a_full_capture_row_present():
    # Settlement: one PARTIAL capture (gap 10000) + one FULL capture (gap 0). Bank is short by the
    # 10000 gap. The full-capture row must NOT disqualify the diagnosis (regression for fix #4).
    line = _bank("line_mix", 140000)
    rows = [_pay("pay_A", 100000, 100000, 90000), _pay("pay_B", 50000, 50000, 50000)]
    inv = investigate(line, None, _rec(line, 150000), rows, ReconIndex(rows))
    assert inv.root_cause == ROOT_CAUSE_PARTIAL_CAPTURE
    assert inv.corrective_entry is not None and inv.corrective_entry["balanced"] is True


def test_one_sided_capture_evidence_abstains():
    # pay_B carries only an authorized amount (captured missing) -> ambiguous evidence. Fail closed:
    # do NOT classify partial_capture or draft a voucher (regression for fix #1).
    line = _bank("line_one", 140000)
    rows = [_pay("pay_A", 100000, 100000, 90000), _pay("pay_B", 50000, 50000, None)]
    inv = investigate(line, None, _rec(line, 150000), rows, ReconIndex(rows))
    assert inv.root_cause != ROOT_CAUSE_PARTIAL_CAPTURE
    assert inv.root_cause == ROOT_CAUSE_UNEXPLAINED
    assert inv.corrective_entry is None


def test_as_int_paise_rejects_non_integer_money():
    assert _as_int_paise(1500, ctx="t") == 1500
    assert _as_int_paise("1500", ctx="t") == 1500
    assert _as_int_paise(1500.0, ctx="t") == 1500  # integer-valued float is fine
    assert _as_int_paise(None, ctx="t") == 0
    assert _as_int_paise("", ctx="t") == 0
    for bad in (True, False, 1.5, float("nan"), float("inf")):
        with pytest.raises(InputError):
            _as_int_paise(bad, ctx="t")


def test_voucher_corrects_variance_guards():
    good = {
        "balanced": True,
        "lines": [
            {"debit_inr": "10.00", "credit_inr": "0.00"},
            {"debit_inr": "0.00", "credit_inr": "10.00"},
        ],
    }
    assert _voucher_corrects_variance(good, 1000) is True  # ₹10.00 == 1000 paise
    assert _voucher_corrects_variance(good, 2000) is False  # wrong size
    assert _voucher_corrects_variance(good, 0) is False  # expected 0 is not a correction
    assert _voucher_corrects_variance(None, 1000) is False  # missing
    assert _voucher_corrects_variance({"balanced": True, "lines": []}, 1000) is False  # empty
    assert _voucher_corrects_variance({"balanced": False, "lines": good["lines"]}, 1000) is False
    subpaise = {
        "balanced": True,
        "lines": [
            {"debit_inr": "10.005", "credit_inr": "0.00"},
            {"debit_inr": "0.00", "credit_inr": "10.005"},
        ],
    }
    assert _voucher_corrects_variance(subpaise, 1000) is False  # sub-paise must not round to a pass


def test_voucher_scorer_is_crash_safe_on_malformed_input():
    # A malformed corrective entry must be REJECTED (return False), never raise — one bad voucher
    # can't be allowed to abort the whole metrics run.
    for bad_lines in (
        [None],                                              # null line
        ["not-a-mapping"],                                   # non-dict line
        [{"debit_inr": True, "credit_inr": "0.00"}],         # boolean amount
        [{"debit_inr": "abc", "credit_inr": "0.00"}],        # non-numeric text
        [{"debit_inr": "NaN", "credit_inr": "0.00"}],        # non-finite
        [{"debit_inr": "Infinity", "credit_inr": "0.00"}],
    ):
        entry = {"balanced": True, "lines": bad_lines}
        assert _voucher_corrects_variance(entry, 1000) is False


def test_voucher_scorer_rejects_ambiguous_double_entry_lines():
    # A line with BOTH sides non-zero, or a single self-balancing line, is not valid double-entry.
    both_sided = {"balanced": True, "lines": [{"debit_inr": "10.00", "credit_inr": "10.00"}]}
    assert _voucher_corrects_variance(both_sided, 1000) is False
    zero_line = {"balanced": True, "lines": [{"debit_inr": "0.00", "credit_inr": "0.00"}]}
    assert _voucher_corrects_variance(zero_line, 1000) is False

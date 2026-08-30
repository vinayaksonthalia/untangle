from datetime import datetime

import pytest

from engine.feegst import fee_gst
from engine.journal import build_journal_entries
from engine.models import ReconRow, ReconciliationResult


def _row(fee, tax, row_id=None):
    return ReconRow("same", "payment", 10000 + fee, fee, tax, 0, 10000, "s", "u",
                    datetime(2026, 1, 1), datetime(2026, 1, 1), False, None, None, "upi", None, row_id)


def test_duplicate_key_uses_nonfirst_physical_row_everywhere():
    rows = [_row(100, 18), _row(700, 126)]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["recon_1"])
    assert fee_gst([rec], rows).total_recoverable_paise == 126
    entry = build_journal_entries([rec], rows)[0]
    assert entry.balanced
    assert any(line.debit_paise == 574 for line in entry.lines)  # 700 fee less 126 GST


def test_caller_row_ids_are_not_trusted_for_physical_identity():
    rows = [_row(100, 18, "duplicate"), _row(700, 126, "duplicate")]
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["recon_1"])
    assert fee_gst([rec], rows).total_recoverable_paise == 126


def test_missing_covered_identity_fails_closed():
    rec = ReconciliationResult("k", [("payment", "same")], 10000, 10000, 0, True, ["missing"])
    with pytest.raises(ValueError):
        fee_gst([rec], [_row(100, 18)])
    with pytest.raises(ValueError):
        build_journal_entries([rec], [_row(100, 18)])

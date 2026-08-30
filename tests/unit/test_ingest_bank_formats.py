from pathlib import Path

import pytest

from engine.ingest import InputError, load_bank


def test_metadata_aliases_dates_commas_and_accounting_markers(tmp_path: Path):
    p = tmp_path / "bank.csv"
    p.write_text(
        "Exported by bank,,,,\n"
        "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        "01/07/2026,NEFT ACME,UTR1,01/07/2026,,1,23,456.78 CR,1\n",
        encoding="utf-8",
    )
    # The deliberately quoted amount is the valid CSV representation of commas.
    p.write_text(
        "Exported by bank,,,,\nDate,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        '01/07/2026,NEFT ACME,UTR1,01/07/2026,,"1,23,456.78 CR",1\n', encoding="utf-8"
    )
    lines = load_bank(str(p))
    assert lines[0].amount_paise == 12345678
    assert lines[0].value_date.isoformat() == "2026-07-01"


def test_malformed_amount_is_actionable(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("Date,Narration,Credit,Debit\n01/07/2026,broken,nope,\n", encoding="utf-8")
    with pytest.raises(InputError, match="could not parse amount"):
        load_bank(str(p))


def test_unknown_encoding_is_rejected(tmp_path: Path):
    p = tmp_path / "bad-encoding.csv"
    p.write_bytes(b"Date,Narration,Credit,Debit\n\xff")
    with pytest.raises(UnicodeDecodeError):
        load_bank(str(p))

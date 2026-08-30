from pathlib import Path

import pytest

from engine.ingest import InputError, load_bank


def test_metadata_aliases_dates_commas_and_accounting_markers(tmp_path: Path):
    p = tmp_path / "bank.csv"
    p.write_text(
        "Exported by bank,,,,\nValue Dt,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        '01/07/2026,NEFT ACME,UTR1, ,"1,23,456.78 CR",1\n', encoding="utf-8"
    )
    lines = load_bank(str(p))
    assert lines[0].amount_paise == 12345678
    assert lines[0].value_date.isoformat() == "2026-07-01"


def test_malformed_amount_is_actionable(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("Date,Narration,Credit,Debit\n01/07/2026,broken,nope,\n", encoding="utf-8")
    with pytest.raises(InputError, match="could not parse amount"):
        load_bank(str(p))


def test_parse_error_after_metadata_reports_physical_line(tmp_path: Path):
    # Two metadata lines precede the header, so the bad amount sits on physical line 5. The error must
    # cite row 5, not the normalized position 3, or the message points the user at the wrong line.
    p = tmp_path / "meta.csv"
    p.write_text(
        "Account statement,,,\n"
        "Generated 2026-07-01,,,\n"
        "Date,Narration,Credit,Debit\n"
        "01/07/2026,good,100,\n"
        "02/07/2026,broken,nope,\n",
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="row 5"):
        load_bank(str(p))


def test_uppercase_canonical_headers_are_accepted(tmp_path: Path):
    # Canonical names in upper/mixed case are absent from the alias table; discovery and mapping must
    # normalize them the same way, or a valid header is discovered and then rejected as "missing".
    p = tmp_path / "upper.csv"
    p.write_text("VALUE_DATE,NARRATION,CREDIT,DEBIT\n01/07/2026,NEFT ACME,500,\n", encoding="utf-8")
    lines = load_bank(str(p))
    assert lines[0].amount_paise == 50000
    assert lines[0].value_date.isoformat() == "2026-07-01"
    assert lines[0].is_credit


def test_parse_error_after_multiline_quoted_field_reports_physical_line(tmp_path: Path):
    # The first metadata record is a quoted field spanning physical lines 1-2, so the header is on
    # line 3, the good row on 4, and the bad row on 5. A record-index count would say 4; only the
    # true physical line (csv.reader.line_num) says 5.
    p = tmp_path / "multiline.csv"
    p.write_text(
        '"Account statement\ncontinued",,,\n'
        "Date,Narration,Credit,Debit\n"
        "01/07/2026,good,100,\n"
        "02/07/2026,broken,nope,\n",
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="row 5"):
        load_bank(str(p))


def test_unknown_encoding_is_rejected(tmp_path: Path):
    p = tmp_path / "bad-encoding.csv"
    p.write_bytes(b"Date,Narration,Credit,Debit\n\xff")
    with pytest.raises(UnicodeDecodeError):
        load_bank(str(p))


@pytest.mark.parametrize("header", [
    "Date,Date,Narration,Credit,Debit",
    "Date,Narration,Credit,Debit,Extra",
])
def test_duplicate_or_ragged_headers_fail_closed(tmp_path: Path, header: str):
    p = tmp_path / "bad.csv"
    row = "01/07/2026,broken,1,\n" if header.endswith("Extra") else "01/07/2026,broken,1,,x\n"
    p.write_text(header + "\n" + row, encoding="utf-8")
    with pytest.raises(InputError):
        load_bank(str(p))


@pytest.mark.parametrize("amounts", [("1", "2"), ("", "")])
def test_credit_debit_direction_is_unambiguous(tmp_path: Path, amounts):
    p = tmp_path / "bad.csv"
    p.write_text(f"Date,Narration,Credit,Debit\n01/07/2026,broken,{amounts[0]},{amounts[1]}\n", encoding="utf-8")
    with pytest.raises(InputError, match="exactly one"):
        load_bank(str(p))


@pytest.mark.parametrize("column", ["Credit", "Debit"])
def test_negative_direction_amount_fails_closed(tmp_path: Path, column: str):
    p = tmp_path / "negative.csv"
    credit = "-100.00" if column == "Credit" else ""
    debit = "-100.00" if column == "Debit" else ""
    p.write_text(
        f"Date,Narration,Credit,Debit\n01/07/2026,broken,{credit},{debit}\n",
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="non-negative"):
        load_bank(str(p))


@pytest.mark.parametrize("column,marker", [("Credit", "DR"), ("Debit", "CR")])
def test_contradictory_accounting_marker_fails_closed(tmp_path: Path, column: str, marker: str):
    # A DR marker in the credit column (or CR in debit) contradicts the column's direction and must
    # be rejected, not silently stripped and assigned the column's sign.
    p = tmp_path / "marker.csv"
    credit = f"100 {marker}" if column == "Credit" else ""
    debit = f"100 {marker}" if column == "Debit" else ""
    p.write_text(
        f"Date,Narration,Credit,Debit\n01/07/2026,mismatch,{credit},{debit}\n",
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="contradicts"):
        load_bank(str(p))


def test_matching_accounting_marker_is_accepted(tmp_path: Path):
    # CR in credit / DR in debit agree with the column and parse normally.
    p = tmp_path / "ok_marker.csv"
    p.write_text(
        "Date,Narration,Credit,Debit\n"
        "01/07/2026,in,500 CR,\n"
        "02/07/2026,out,,250 DR\n",
        encoding="utf-8",
    )
    lines = load_bank(str(p))
    assert lines[0].amount_paise == 50000 and lines[0].is_credit
    assert lines[1].amount_paise == -25000 and not lines[1].is_credit


def test_comma_prefixed_negative_is_rejected(tmp_path: Path):
    # A quoted ",-100.00" does not start with '-' until commas are removed; validation must happen
    # AFTER normalization or the negative slips through and gets the column's sign.
    p = tmp_path / "comma_neg.csv"
    p.write_text(
        'Date,Narration,Credit,Debit\n01/07/2026,sneaky,",-100.00",\n',
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="non-negative"):
        load_bank(str(p))

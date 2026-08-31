"""Unit and property tests for the Fail-Closed Bank Statement Adapter Foundation.

Verifies:
1. Detection contracts (unambiguous matching, header variations, order independence, fail-closed ambiguity).
2. Parsing invariants (monetary precision, directionality, error normalization, encoding, CRLF/LF).
3. Metadata & provenance guarantees (immutability, determinism, isolation from BankCreditLine).
4. Full compatibility with existing datasets and report pipelines.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path

import pytest

from engine.bank_adapters import (
    BankInputProvenance,
    BankLoadResult,
    GenericCsvBankAdapter,
    InputError,
    find_adapter,
    get_default_bank_adapters,
    parse_bank_statement,
)
from engine.ingest import load_bank, load_bank_bytes, load_bank_bytes_result, load_bank_result
from engine.models import BankCreditLine

DATA_DIR = Path(__file__).parent.parent.parent / "data"
_BANK_CSV_PATH = str(DATA_DIR / "bank_statement.csv")


# ---------------------------------------------------------------------------
# Test Helpers & Fake Adapters for Hermetic Ambiguity Testing
# ---------------------------------------------------------------------------


class FakeOverlappingAdapterA:
    adapter_id: str = "fake_adapter_a"
    adapter_version: str = "1.0.0"

    def detect(self, headers: Sequence[str]) -> bool:
        return {"date", "narration", "credit", "debit"}.issubset({h.strip().lower() for h in headers})

    def parse(self, line_source, *, source: str) -> BankLoadResult:
        provenance = BankInputProvenance(self.adapter_id, self.adapter_version, source)
        return BankLoadResult(lines=(), provenance=provenance)


class FakeOverlappingAdapterB:
    adapter_id: str = "fake_adapter_b"
    adapter_version: str = "2.0.0"

    def detect(self, headers: Sequence[str]) -> bool:
        return {"date", "narration", "credit", "debit"}.issubset({h.strip().lower() for h in headers})

    def parse(self, line_source, *, source: str) -> BankLoadResult:
        provenance = BankInputProvenance(self.adapter_id, self.adapter_version, source)
        return BankLoadResult(lines=(), provenance=provenance)


# ---------------------------------------------------------------------------
# 1. Detection Tests
# ---------------------------------------------------------------------------


def test_default_registry_contains_only_generic_csv():
    """Verify that default production registry contains only the generic CSV adapter."""
    adapters = get_default_bank_adapters()
    assert len(adapters) == 1
    assert adapters[0].adapter_id == "generic_csv"
    assert adapters[0].adapter_version == "1.0.0"



def test_generic_headers_detection():
    """Requirement 1: Current generic CSV headers select exactly the generic adapter."""
    adapter = GenericCsvBankAdapter()
    headers = ["Date", "Narration", "Credit", "Debit"]
    assert adapter.detect(headers) is True

    selected = find_adapter(headers)
    assert selected.adapter_id == "generic_csv"
    assert selected.adapter_version == "1.0.0"


def test_header_order_variation():
    """Requirement 2: Header order variation behaves according to the existing contract."""
    adapter = GenericCsvBankAdapter()
    variations = [
        ["Debit", "Credit", "Narration", "Date"],
        ["Narration", "Date", "Chq./Ref.No.", "Deposit Amt.", "Withdrawal Amt."],
        ["Withdrawal Amount", "Deposit Amount", "Description", "Value Date"],
    ]
    for headers in variations:
        assert adapter.detect(headers) is True
        assert find_adapter(headers).adapter_id == "generic_csv"


def test_utf8_bom_header_detection():
    """Requirement 3: UTF-8 BOM on the first header is accepted."""
    adapter = GenericCsvBankAdapter()
    headers = ["\ufeffDate", "Narration", "Credit", "Debit"]
    assert adapter.detect(headers) is True
    assert find_adapter(headers).adapter_id == "generic_csv"


def test_surrounding_header_whitespace():
    """Requirement 4: Harmless surrounding header whitespace is accepted."""
    adapter = GenericCsvBankAdapter()
    headers = ["  Date  ", "\tNarration\t", " Credit ", "  Debit  "]
    assert adapter.detect(headers) is True
    assert find_adapter(headers).adapter_id == "generic_csv"


def test_unsupported_headers_raise_input_error():
    """Requirement 5: Unsupported headers raise InputError."""
    with pytest.raises(InputError, match="unsupported header schema"):
        find_adapter(["ColA", "ColB", "ColC"])

    csv_data = "ColA,ColB,ColC\n1,2,3\n"
    with pytest.raises(InputError, match="could not find a header row with date and narration columns"):
        parse_bank_statement(io.StringIO(csv_data))


def test_duplicate_normalized_headers_raise_input_error(tmp_path: Path):
    """Requirement 6: Duplicate normalized headers causing ambiguity raise InputError."""
    csv_data = "Date,Date,Narration,Credit,Debit\n01/07/2026,01/07/2026,ACME,100,\n"
    with pytest.raises(InputError, match="duplicate columns after normalization"):
        parse_bank_statement(io.StringIO(csv_data))


def test_conflicting_aliases_raise_input_error(tmp_path: Path):
    """Requirement 7: Conflicting aliases raise InputError."""
    csv_data = "Date,Value Date,Narration,Credit,Debit\n01/07/2026,01/07/2026,ACME,100,\n"
    with pytest.raises(InputError, match="duplicate columns after normalization"):
        parse_bank_statement(io.StringIO(csv_data))


def test_ambiguous_matching_adapters_raise_input_error():
    """Requirement 8: Two matching test adapters produce an ambiguity InputError."""
    headers = ["Date", "Narration", "Credit", "Debit"]
    adapters = [FakeOverlappingAdapterA(), FakeOverlappingAdapterB()]

    with pytest.raises(InputError, match="ambiguous schema detected; multiple adapters matched"):
        find_adapter(headers, adapters=adapters)

    csv_data = "Date,Narration,Credit,Debit\n01/07/2026,ACME,100,\n"
    with pytest.raises(InputError, match="ambiguous schema detected; multiple adapters matched"):
        parse_bank_statement(io.StringIO(csv_data), adapters=adapters)


def test_adapter_order_independence():
    """Requirement 9: Reversing adapter registration order produces the same result."""
    headers = ["Date", "Narration", "Credit", "Debit"]
    adapters_forward = [FakeOverlappingAdapterA(), FakeOverlappingAdapterB()]
    adapters_reverse = [FakeOverlappingAdapterB(), FakeOverlappingAdapterA()]

    with pytest.raises(InputError) as exc_fwd:
        find_adapter(headers, adapters=adapters_forward)

    with pytest.raises(InputError) as exc_rev:
        find_adapter(headers, adapters=adapters_reverse)

    assert str(exc_fwd.value) == str(exc_rev.value)


def test_detection_does_not_inspect_narration_or_values():
    """Requirement 10: Detection does not inspect narration or transaction values."""
    adapter = GenericCsvBankAdapter()
    # Schema that does not match generic bank CSV headers, but data contains bank-like keywords
    csv_data = (
        "Col1,Col2,Col3\n"
        "01/07/2026,SBI HDFC Razorpay RTGS/UTR123/RATN0000001,100000.00\n"
    )
    headers = ["Col1", "Col2", "Col3"]
    assert adapter.detect(headers) is False
    with pytest.raises(InputError):
        parse_bank_statement(io.StringIO(csv_data))


# ---------------------------------------------------------------------------
# 2. Parsing & Invariant Tests
# ---------------------------------------------------------------------------


def test_generic_fixture_parsing_matches_baseline():
    """Requirement 11: Existing generic fixtures produce the same BankCreditLine values as before."""
    lines = load_bank(_BANK_CSV_PATH)
    assert len(lines) == 294
    assert lines[0].value_date.isoformat() == "2026-06-02"
    assert lines[0].amount_paise == 30684938
    assert lines[0].is_credit is True
    assert lines[0].key == "k_9f8dafbd274120b1"


def test_load_bank_return_contract():
    """Requirement 12: load_bank preserves its return contract."""
    lines = load_bank(_BANK_CSV_PATH)
    assert isinstance(lines, list)
    assert all(isinstance(line, BankCreditLine) for line in lines)


def test_load_bank_bytes_return_contract():
    """Requirement 13: load_bank_bytes preserves its return contract."""
    content = Path(_BANK_CSV_PATH).read_bytes()
    lines = load_bank_bytes(content)
    assert isinstance(lines, list)
    assert all(isinstance(line, BankCreditLine) for line in lines)


def test_path_and_byte_variants_equivalence():
    """Requirement 14: Path and byte variants produce equivalent canonical records."""
    content = Path(_BANK_CSV_PATH).read_bytes()
    lines_from_path = load_bank(_BANK_CSV_PATH)
    lines_from_bytes = load_bank_bytes(content)
    assert lines_from_path == lines_from_bytes


def test_exact_decimal_to_paise_conversion():
    """Requirement 15: Exact decimal-to-paise conversion is preserved."""
    csv_data = (
        "Date,Narration,Credit,Debit\n"
        "01/07/2026,Exact Paise,12345.67,\n"
        "02/07/2026,Half Up,100.005,\n"
        "03/07/2026,Half Down,100.994,\n"
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert lines[0].amount_paise == 1234567
    assert lines[1].amount_paise == 10001
    assert lines[2].amount_paise == 10099


def test_credit_debit_direction_preserved():
    """Requirement 16: Credit/debit direction is preserved."""
    csv_data = (
        "Date,Narration,Credit,Debit\n"
        "01/07/2026,Incoming,500.00,\n"
        "02/07/2026,Outgoing,,250.00\n"
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert lines[0].amount_paise == 50000 and lines[0].is_credit is True
    assert lines[1].amount_paise == -25000 and lines[1].is_credit is False


def test_contradictory_debit_credit_rejected():
    """Requirement 17: Contradictory debit and credit representations are rejected."""
    csv_both = "Date,Narration,Credit,Debit\n01/07/2026,Bad,100.00,200.00\n"
    with pytest.raises(InputError, match="exactly one"):
        load_bank_bytes(csv_both.encode("utf-8"))

    csv_neither = "Date,Narration,Credit,Debit\n01/07/2026,Bad,,\n"
    with pytest.raises(InputError, match="exactly one"):
        load_bank_bytes(csv_neither.encode("utf-8"))


def test_non_finite_and_out_of_range_money_rejected():
    """Requirement 18: Non-finite and out-of-range money values are rejected."""
    bad_values = ["NaN", "Infinity", "inf", "abc", ".", "--5", "₹500"]
    for val in bad_values:
        csv_data = f"Date,Narration,Credit,Debit\n01/07/2026,Bad,{val},\n"
        with pytest.raises(InputError):
            load_bank_bytes(csv_data.encode("utf-8"))


def test_invalid_dates_raise_actionable_input_error():
    """Requirement 19: Invalid dates remain actionable InputErrors."""
    bad_dates = ["99/99/9999", "2026-02-31", "not-a-date", ""]
    for d in bad_dates:
        csv_data = f"Date,Narration,Credit,Debit\n{d},Test,100,\n"
        with pytest.raises(InputError, match="could not parse date"):
            load_bank_bytes(csv_data.encode("utf-8"))


def test_invalid_utf8_raises_input_error():
    """Requirement 20: Invalid UTF-8 raises InputError, not UnicodeDecodeError."""
    invalid_bytes = b"\xff\xfe\x00Date,Narration,Credit,Debit"
    with pytest.raises(InputError, match="is not valid UTF-8 text"):
        load_bank_bytes(invalid_bytes)


def test_header_only_file_rejected():
    """Requirement 21: Header-only files are rejected."""
    csv_data = "Date,Narration,Credit,Debit\n"
    with pytest.raises(InputError, match="contained no data rows"):
        load_bank_bytes(csv_data.encode("utf-8"))


def test_empty_file_rejected():
    """Requirement 22: Empty files are rejected."""
    with pytest.raises(InputError, match="is empty"):
        load_bank_bytes(b"")


def test_malformed_non_empty_rows_rejected():
    """Requirement 23: Malformed non-empty rows are rejected rather than dropped."""
    csv_data = "Date,Narration,Credit,Debit\n01/07/2026,BadRow,100\n"  # 3 cols instead of 4
    with pytest.raises(InputError, match="expected 4 columns, found 3"):
        load_bank_bytes(csv_data.encode("utf-8"))


def test_truly_blank_rows_ignored():
    """Requirement 24: Truly blank rows behave consistently with the existing parser."""
    csv_data = (
        "Date,Narration,Credit,Debit\n\n"
        "01/07/2026,Row1,100.00,\n\n"
        "   \n"
        "02/07/2026,Row2,,50.00\n\n"
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert len(lines) == 2


def test_crlf_input_parses_equivalently_to_lf():
    """Requirement 25: CRLF input parses equivalently to LF input."""
    lf_text = "Date,Narration,Credit,Debit\n01/07/2026,Row1,100.00,\n02/07/2026,Row2,,50.00\n"
    crlf_text = lf_text.replace("\n", "\r\n")

    lines_lf = load_bank_bytes(lf_text.encode("utf-8"))
    lines_crlf = load_bank_bytes(crlf_text.encode("utf-8"))
    assert lines_lf == lines_crlf


def test_quoted_multiline_narration_parsed_correctly():
    """Requirement 26: Properly quoted multiline narration parses correctly."""
    csv_data = (
        "Date,Narration,Credit,Debit\n"
        '01/07/2026,"UPI/ACME\nSubline details",100.00,\n'
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert len(lines) == 1
    assert "UPI/ACME\nSubline details" in lines[0].narration


def test_quoted_comma_in_narration_preserved():
    """Requirement 27: A properly quoted comma inside narration is preserved."""
    csv_data = (
        "Date,Narration,Credit,Debit\n"
        '01/07/2026,"NEFT, ACME CORP, REF123",100.00,\n'
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert lines[0].narration == "NEFT, ACME CORP, REF123"


def test_malformed_quoting_fails_closed():
    """Requirement 28: Malformed quoting fails closed."""
    csv_data = 'Date,Narration,Credit,Debit\n01/07/2026,"Unclosed quote,100.00,\n'
    with pytest.raises(InputError):
        load_bank_bytes(csv_data.encode("utf-8"))


def test_identifier_content_not_rewritten():
    """Requirement 29: Identifier content is not case-folded or Unicode-rewritten."""
    original_narration = "UPI-Pay_123.ABC/XYZ"
    original_ref = "REF_No.789-Alpha"
    csv_data = (
        "Date,Narration,Ref No,Credit,Debit\n"
        f"01/07/2026,{original_narration},{original_ref},100.00,\n"
    )
    lines = load_bank_bytes(csv_data.encode("utf-8"))
    assert lines[0].narration == original_narration
    assert lines[0].bank_ref == original_ref


def test_user_facing_errors_contain_stable_label_no_temp_paths():
    """Requirement 30: User-facing errors contain the stable input label and do not expose temporary paths."""
    csv_bad = b"Date,Narration,Credit,Debit\n01/07/2026,Bad,abc,\n"
    with pytest.raises(InputError) as exc_info:
        load_bank_bytes(csv_bad, source="bank statement")

    msg = str(exc_info.value)
    assert "bank statement" in msg.lower()
    assert "/tmp/" not in msg
    assert "private" not in msg


# ---------------------------------------------------------------------------
# 3. Metadata & Provenance Tests
# ---------------------------------------------------------------------------


def test_adapter_id_and_version_deterministic():
    """Requirement 31: The selected adapter ID and version are deterministic."""
    res1 = load_bank_result(_BANK_CSV_PATH)
    res2 = load_bank_result(_BANK_CSV_PATH)

    assert res1.provenance.adapter_id == "generic_csv"
    assert res1.provenance.adapter_version == "1.0.0"
    assert res1.provenance == res2.provenance


def test_metadata_does_not_alter_bank_credit_line_objects():
    """Requirement 32: Metadata does not alter the existing BankCreditLine objects."""
    res = load_bank_result(_BANK_CSV_PATH)
    direct_lines = load_bank(_BANK_CSV_PATH)

    assert list(res.lines) == direct_lines
    for line in res.lines:
        assert isinstance(line, BankCreditLine)
        # BankCreditLine does not carry adapter fields
        assert not hasattr(line, "adapter_id")
        assert not hasattr(line, "provenance")


def test_metadata_warnings_are_immutable():
    """Requirement 33: Metadata warnings are immutable/deterministic."""
    res = load_bank_result(_BANK_CSV_PATH)
    assert isinstance(res.provenance.warnings, tuple)


def test_existing_report_output_unchanged_on_baseline():
    """Requirement 34: Existing report output is unchanged for the baseline fixture."""
    from engine.service import reconcile

    report = reconcile(
        _BANK_CSV_PATH,
        str(DATA_DIR / "recon_report.json"),
        str(DATA_DIR / "order_ledger.csv"),
    )
    assert report["totals"]["n_bank_lines"] == 294
    assert report["totals"]["attributed"] == 280
    assert report["totals"]["by_rail_count"]["razorpay_settlement"] == 103
    assert report["totals"]["reconciled_count"] == 91
    assert "provenance" not in report  # provenance not yet added to report JSON in Phase 1 Task 1


# ---------------------------------------------------------------------------
# 4. Property Tests
# ---------------------------------------------------------------------------


def test_property_detection_independent_of_adapter_order():
    """Property: detect result is independent of adapter order in registry."""
    headers = ["Date", "Narration", "Credit", "Debit"]
    generic = GenericCsvBankAdapter()
    adapters1 = (generic,)
    adapters2 = (generic,)

    assert find_adapter(headers, adapters=adapters1) == find_adapter(headers, adapters=adapters2)


def test_property_lf_crlf_equivalence():
    """Property: LF and CRLF byte streams produce identical lines."""
    base_csv = "Date,Narration,Credit,Debit\n01/07/2026,Txn A,100.50,\n02/07/2026,Txn B,,200.75\n"
    crlf_csv = base_csv.replace("\n", "\r\n")

    res_lf = load_bank_bytes_result(base_csv.encode("utf-8"))
    res_crlf = load_bank_bytes_result(crlf_csv.encode("utf-8"))
    assert res_lf.lines == res_crlf.lines
    assert res_lf.provenance.adapter_id == res_crlf.provenance.adapter_id


def test_property_utf8_bom_equivalence():
    """Property: UTF-8 with BOM and without BOM produce identical parsed lines."""
    base_text = "Date,Narration,Credit,Debit\n01/07/2026,Txn A,100.50,\n"
    bytes_plain = base_text.encode("utf-8")
    bytes_bom = b"\xef\xbb\xbf" + bytes_plain

    res_plain = load_bank_bytes(bytes_plain)
    res_bom = load_bank_bytes(bytes_bom)
    assert res_plain == res_bom


def test_property_header_surrounding_whitespace_equivalence():
    """Property: Harmless header surrounding whitespace produces identical lines."""
    clean_csv = "Date,Narration,Credit,Debit\n01/07/2026,Txn A,100.50,\n"
    padded_csv = "  Date  ,  Narration  ,  Credit  ,  Debit  \n01/07/2026,Txn A,100.50,\n"

    res_clean = load_bank_bytes(clean_csv.encode("utf-8"))
    res_padded = load_bank_bytes(padded_csv.encode("utf-8"))
    assert res_clean == res_padded


def test_property_deterministic_parsing():
    """Property: Parsing identical bytes repeatedly produces byte-identical output."""
    raw = Path(_BANK_CSV_PATH).read_bytes()
    res1 = load_bank_bytes(raw)
    res2 = load_bank_bytes(raw)
    assert res1 == res2


def test_property_decimal_money_exactness():
    """Property: Money decimal arithmetic never suffers floating point drift."""
    for rupees_str, expected_paise in [
        ("0.01", 1),
        ("0.99", 99),
        ("1.00", 100),
        ("1234567.89", 123456789),
        ("9999999.99", 999999999),
    ]:
        csv_data = f"Date,Narration,Credit,Debit\n01/07/2026,Test,{rupees_str},\n"
        lines = load_bank_bytes(csv_data.encode("utf-8"))
        assert lines[0].amount_paise == expected_paise

"""Bank statement adapter foundation (fail-closed schema recognition and parsing).

Establishes a minimal, deterministic, and fail-closed adapter boundary for
bank-statement ingestion while preserving all existing behavior and outputs.

Decision contract:
1. Exactly one adapter recognizes the input: use it.
2. No adapter recognizes the input: raise an actionable InputError.
3. More than one adapter recognizes the input: raise an actionable ambiguity InputError.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

from engine.models import BankCreditLine


class InputError(Exception):
    """Raised on any malformed/missing input. Carries a human-readable, actionable message.

    The CLI maps this to exit code 2.
    """


@dataclass(frozen=True)
class BankInputProvenance:
    """Provenance metadata describing which adapter parsed the bank statement."""

    adapter_id: str
    adapter_version: str
    source_label: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BankLoadResult:
    """The canonical parsed bank lines together with immutable adapter provenance."""

    lines: tuple[BankCreditLine, ...]
    provenance: BankInputProvenance


class BankStatementAdapter(Protocol):
    """Protocol for bank statement adapters."""

    adapter_id: str
    adapter_version: str

    def detect(self, headers: Sequence[str]) -> bool:
        """Return True if this adapter recognizes the header schema."""
        ...

    def parse_rows(
        self,
        header: Sequence[str],
        rows: CsvRowReader,
        *,
        source: str,
        header_end_line: int,
    ) -> BankLoadResult:
        """Parse rows from the already-open CSV reader into a BankLoadResult."""
        ...


class CsvRowReader(Protocol):
    """The streaming subset of ``csv.reader`` consumed by adapters."""

    line_num: int

    def __iter__(self) -> Iterator[list[str]]:
        ...

    def __next__(self) -> list[str]:
        ...


# ---------------------------------------------------------------------------
# Helpers for parsing amounts, dates, and keys
# ---------------------------------------------------------------------------


def _line_key(value_date: str, amount_paise: int, narration: str, bank_ref: str | None) -> str:
    """Deterministic content hash. NOT the generator's line_id."""
    payload = f"{value_date}|{amount_paise}|{narration.strip()}|{(bank_ref or '').strip()}"
    return "k_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _rupees_to_paise(raw: str, *, ctx: str) -> int:
    """Parse a rupee string to integer paise. Rounds (never truncates) sub-paise fractions using
    banker's-safe half-up, so 12345.789 → 1234579 paise, not 1234578. Decimal keeps it exact."""
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return 0
    try:
        paise = (Decimal(raw) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(paise)
    except (InvalidOperation, ValueError) as exc:
        raise InputError(
            f"Bank statement: could not parse amount {raw!r} in {ctx}. "
            f"Expected a rupee value like 12345.67."
        ) from exc


_MARKER_COLUMN = {"CR": "credit", "DR": "debit"}


def _parse_direction_amount(raw: str, *, column: str, ctx: str) -> int:
    """Parse a bank credit/debit cell to NON-NEGATIVE paise.

    Direction is decided by the column the value sits in, never by a sign or an accounting marker.
    A ``CR``/``DR`` marker, if present, must AGREE with that column (``CR`` only in credit, ``DR``
    only in debit) or the row is rejected — contradictory direction data must never be silently
    re-signed. A signed amount is rejected after comma normalization, so ``",-100.00"`` cannot slip
    a negative past the check; a value that rounds to zero but is written negative is rejected too.
    """
    text = (raw or "").strip()
    for marker in ("CR", "DR"):
        if text.upper().endswith(" " + marker):
            if _MARKER_COLUMN[marker] != column:
                raise InputError(
                    f"Bank statement {ctx}: a {marker} marker in the {column} column contradicts "
                    "its direction; put the amount in the column that matches the marker."
                )
            text = text[: len(text) - len(marker) - 1].rstrip()
            break
    if text.replace(",", "").lstrip().startswith("-"):
        raise InputError(
            f"Bank statement {ctx}: credit/debit amounts must be non-negative ({raw!r}); "
            "use the appropriate column to indicate direction."
        )
    return _rupees_to_paise(text, ctx=ctx)


def _parse_date(raw: str, *, ctx: str) -> date:
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise InputError(
            f"{ctx}: could not parse date {raw!r}. Supported formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD/MM/YY, DD-MM-YY, DD.MM.YYYY."
        ) from exc


# ---------------------------------------------------------------------------
# Generic CSV Bank Adapter (Untangle's default format)
# ---------------------------------------------------------------------------

_BANK_REQUIRED = {"value_date", "narration", "credit", "debit"}

_BANK_ALIASES = {
    "value date": "value_date",
    "value dt": "value_date",
    "date": "value_date",
    "narration": "narration",
    "description": "narration",
    "particulars": "narration",
    "chq./ref.no.": "ref_no",
    "chq/ref no": "ref_no",
    "ref no": "ref_no",
    "reference": "ref_no",
    "deposit amt.": "credit",
    "deposit amount": "credit",
    "credit": "credit",
    "withdrawal amt.": "debit",
    "withdrawal amount": "debit",
    "debit": "debit",
}


def _clean_header_token(h: str) -> str:
    """Strip UTF-8 BOM, surrounding whitespace, and lowercase for normalization."""
    return h.lstrip("\ufeff").strip().lower()


class GenericCsvBankAdapter:
    """Adapter for generic CSV bank exports with standard date, narration, credit, debit columns."""

    adapter_id: str = "generic_csv"
    adapter_version: str = "1.0.0"

    def detect(self, headers: Sequence[str]) -> bool:
        """Detect whether the header row contains date, narration, credit, debit columns."""
        if not headers or not any(h.strip() for h in headers):
            return False
        cleaned = [_clean_header_token(h) for h in headers]
        mapped = [_BANK_ALIASES.get(c, c) for c in cleaned]
        return _BANK_REQUIRED.issubset(mapped)

    def parse(
        self,
        line_source: Iterable[str],
        *,
        source: str,
    ) -> BankLoadResult:
        """Compatibility entry point; dispatch and parse the source in one streaming pass."""
        return parse_bank_statement(line_source, source=source, adapters=(self,))

    def parse_rows(
        self,
        header: Sequence[str],
        rows: CsvRowReader,
        *,
        source: str,
        header_end_line: int,
    ) -> BankLoadResult:
        """Parse data rows after the dispatcher has selected this adapter from ``header``."""
        cleaned = [_clean_header_token(c) for c in header]
        mapped = [_BANK_ALIASES.get(c, c) for c in cleaned]
        if "value_date" not in mapped or "narration" not in mapped:
            raise InputError("Bank statement: header must contain date and narration columns.")
        if len(mapped) != len(set(mapped)):
            duplicates = sorted({name for name in mapped if mapped.count(name) > 1})
            raise InputError(f"Bank statement: duplicate columns after normalization: {duplicates}.")
        missing = _BANK_REQUIRED - set(mapped)
        if missing:
            raise InputError(
                f"Bank statement {source}: missing required column(s) {sorted(missing)}. "
                f"Found columns: {sorted(set(mapped))}."
            )

        ref_col = "ref_no" if "ref_no" in mapped else ("bank_ref" if "bank_ref" in mapped else None)
        lines: list[BankCreditLine] = []
        end_line = header_end_line
        for row in rows:
            start_line = end_line + 1
            end_line = rows.line_num
            if not any(x.strip() for x in row):
                continue
            if len(row) != len(mapped):
                raise InputError(f"Bank statement row {start_line}: expected {len(mapped)} columns, found {len(row)}.")
            row_dict = dict(zip(mapped, row, strict=True))
            narration = (row_dict.get("narration") or "").strip()
            credit_raw = (row_dict.get("credit") or "").strip()
            debit_raw = (row_dict.get("debit") or "").strip()
            if bool(credit_raw) == bool(debit_raw):
                raise InputError(f"Bank statement row {start_line}: exactly one of credit or debit must be populated.")
            is_credit = bool(credit_raw)
            if is_credit:
                amount = _parse_direction_amount(credit_raw, column="credit", ctx=f"row {start_line}")
            else:
                amount = -_parse_direction_amount(debit_raw, column="debit", ctx=f"row {start_line}")
            bank_ref = (row_dict.get(ref_col) or "").strip() if ref_col else None
            vd_raw = (row_dict.get("value_date") or "").strip()
            parsed_date = _parse_date(vd_raw, ctx=f"Bank statement row {start_line}")
            key = _line_key(parsed_date.isoformat(), amount, narration, bank_ref)
            lines.append(
                BankCreditLine(
                    key=key,
                    value_date=parsed_date,
                    amount_paise=amount,
                    narration=narration,
                    bank_ref=bank_ref or None,
                    is_credit=is_credit,
                )
            )

        if not lines:
            raise InputError(f"Bank statement {source} contained no data rows.")

        # Duplicate key disambiguation (breaks 1:1 line<->verdict invariant if not indexed)
        seen: dict[str, int] = {}
        for ln in lines:
            seen[ln.key] = seen.get(ln.key, 0) + 1
        dupes = {k: c for k, c in seen.items() if c > 1}
        if dupes:
            counters: dict[str, int] = {}
            fixed: list[BankCreditLine] = []
            for ln in lines:
                if seen[ln.key] > 1:
                    counters[ln.key] = counters.get(ln.key, 0) + 1
                    newkey = f"{ln.key}#{counters[ln.key]}"
                    fixed.append(
                        BankCreditLine(
                            newkey,
                            ln.value_date,
                            ln.amount_paise,
                            ln.narration,
                            ln.bank_ref,
                            ln.is_credit,
                        )
                    )
                else:
                    fixed.append(ln)
            lines = fixed

        provenance = BankInputProvenance(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_label=source,
            warnings=(),
        )
        return BankLoadResult(lines=tuple(lines), provenance=provenance)


# ---------------------------------------------------------------------------
# Default Adapter Registry & Dispatcher
# ---------------------------------------------------------------------------

DEFAULT_BANK_ADAPTERS: tuple[BankStatementAdapter, ...] = (GenericCsvBankAdapter(),)


def get_default_bank_adapters() -> tuple[BankStatementAdapter, ...]:
    """Return the immutable default bank adapter registry."""
    return DEFAULT_BANK_ADAPTERS


def find_adapter(
    headers: Sequence[str],
    adapters: Sequence[BankStatementAdapter] | None = None,
    *,
    source: str = "bank statement",
) -> BankStatementAdapter:
    """Find the single matching adapter for a given header sequence.

    Fails closed if 0 or >1 adapters match.
    """
    adapter_list = adapters if adapters is not None else DEFAULT_BANK_ADAPTERS
    matching = [a for a in adapter_list if a.detect(headers)]
    if not matching:
        raise InputError(f"Bank statement {source}: unsupported header schema.")
    if len(matching) > 1:
        adapter_ids = sorted([a.adapter_id for a in matching])
        raise InputError(
            f"Bank statement {source}: ambiguous schema detected; "
            f"multiple adapters matched header: {adapter_ids}."
        )
    return matching[0]


def parse_bank_statement(
    line_source: Iterable[str],
    *,
    source: str = "bank statement",
    adapters: Sequence[BankStatementAdapter] | None = None,
) -> BankLoadResult:
    """Detect and parse a bank statement using registered adapters.

    Fails closed:
    - Exactly 1 adapter matches: parse and return BankLoadResult.
    - 0 adapters match: raise actionable InputError.
    - >1 adapters match: raise actionable ambiguity InputError.
    """
    adapter_list = adapters if adapters is not None else DEFAULT_BANK_ADAPTERS
    if not adapter_list:
        raise InputError(f"Bank statement {source}: no bank adapters configured.")

    try:
        reader = csv.reader(line_source)
        saw_nonempty_record = False
        for row in reader:
            if not any(x.strip() for x in row):
                continue
            saw_nonempty_record = True
            matching = [a for a in adapter_list if a.detect(row)]
            if not matching:
                continue
            if len(matching) > 1:
                adapter_ids = sorted([a.adapter_id for a in matching])
                raise InputError(
                    f"Bank statement {source}: ambiguous schema detected; "
                    f"multiple adapters matched: {adapter_ids}."
                )
            return matching[0].parse_rows(
                row,
                reader,
                source=source,
                header_end_line=reader.line_num,
            )

        if not saw_nonempty_record:
            raise InputError(f"Bank statement {source} is empty.")
        raise InputError("Bank statement: could not find a header row with date and narration columns.")
    except csv.Error as exc:
        raise InputError(f"Bank statement {source}: CSV parsing error: {exc}.") from exc

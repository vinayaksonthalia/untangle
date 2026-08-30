"""Load and validate the three input artifacts.

Isolation (constitution III): this module reads ONLY the caller-supplied
bank/recon/ledger files. It never imports ``generator`` and never reads the blind
answer key (the eval-only labels file lives under data/ and is off-limits here).

The stable per-line key is a content hash of (value_date, amount_paise,
narration, bank_ref). The generator's ``line_id`` column, if present, is
deliberately ignored — using it would leak a key that does not exist on a
real bank statement and could act as an attribution shortcut.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from engine.models import BankCreditLine, OrderLedgerEntry, ReconRow


class InputError(Exception):
    """Raised on any malformed/missing input. Carries a human-readable, actionable message.

    The CLI maps this to exit code 2.
    """


# ---------------------------------------------------------------------------
# Helpers
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


def _epoch_to_dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    try:
        # Convert in UTC, then drop tzinfo: the rest of the engine uses naive datetimes
        # (see _parse_dt), and a naive-vs-aware comparison would raise. Using local time here
        # made settlement dates host-timezone-dependent — a determinism break for a tool whose
        # whole pitch is byte-identical, re-derivable output.
        return datetime.fromtimestamp(int(v), tz=UTC).replace(tzinfo=None)
    except (ValueError, OSError, TypeError):
        return None


def _parse_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _as_int_paise(v, *, ctx: str) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (ValueError, TypeError) as exc:
        raise InputError(f"{ctx}: expected an integer paise value, got {v!r}.") from exc


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

_BANK_REQUIRED = {"value_date", "narration", "credit", "debit"}

# Common Indian bank-export labels. This is deliberately a format adapter, not a
# claim that Untangle has validated any particular bank's production export.
_BANK_ALIASES = {
    "value date": "value_date", "value dt": "value_date", "date": "value_date",
    "narration": "narration", "description": "narration", "particulars": "narration",
    "chq./ref.no.": "ref_no", "chq/ref no": "ref_no", "ref no": "ref_no", "reference": "ref_no",
    "deposit amt.": "credit", "deposit amount": "credit", "credit": "credit",
    "withdrawal amt.": "debit", "withdrawal amount": "debit", "debit": "debit",
}


def _normalise_bank_rows(
    line_source: Iterable[str],
) -> tuple[list[str], Iterator[tuple[int, dict[str, str]]]]:
    """Find a bank header after optional metadata and stream the mapped data rows.

    Reads ``line_source`` (a file handle or any iterable of physical lines) through a single
    ``csv.reader`` pass. Only metadata up to the header is examined during discovery; data rows are
    then yielded lazily, so the whole export is never held as records AND dictionaries at once. Each
    yielded row carries its one-based physical starting line (``csv.reader.line_num`` — correct even
    when a quoted field spans several physical lines), so parsing diagnostics cite the real line.
    """
    reader = csv.reader(line_source)
    end_line = 0  # physical line where the previous record ended
    mapped: list[str] | None = None
    for row in reader:
        end_line = reader.line_num
        # Use the SAME normalized (lower-cased) key for both discovery and mapping so an uppercase or
        # mixed-case canonical header (e.g. VALUE_DATE) is not discovered and then rejected as missing.
        if {_BANK_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in row} >= {"value_date", "narration"}:
            mapped = [_BANK_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in row]
            break
    if mapped is None:
        raise InputError("Bank statement: could not find a header row with date and narration columns.")
    if "value_date" not in mapped or "narration" not in mapped:
        raise InputError("Bank statement: header must contain date and narration columns.")
    if len(mapped) != len(set(mapped)):
        duplicates = sorted({name for name in mapped if mapped.count(name) > 1})
        raise InputError(f"Bank statement: duplicate columns after normalization: {duplicates}.")

    def _data_rows() -> Iterator[tuple[int, dict[str, str]]]:
        nonlocal end_line
        for row in reader:
            start_line = end_line + 1
            end_line = reader.line_num
            if not any(x.strip() for x in row):
                continue
            if len(row) != len(mapped):
                raise InputError(f"Bank statement row {start_line}: expected {len(mapped)} columns, found {len(row)}.")
            yield start_line, dict(zip(mapped, row, strict=True))

    return mapped, _data_rows()


def _load_bank_text(fh: Iterable[str], source: str) -> list[BankCreditLine]:
    # Stream rows straight from the handle — no records list or dictionaries list is materialized.
    mapped_fields, normalized_rows = _normalise_bank_rows(fh)
    fields = set(mapped_fields)
    missing = _BANK_REQUIRED - fields
    if missing:
        raise InputError(
            f"Bank statement {source}: missing required column(s) {sorted(missing)}. "
            f"Found columns: {sorted(fields)}."
        )
    ref_col = "ref_no" if "ref_no" in fields else ("bank_ref" if "bank_ref" in fields else None)
    lines: list[BankCreditLine] = []
    for line_no, row in normalized_rows:
        narration = (row.get("narration") or "").strip()
        credit_raw = (row.get("credit") or "").strip()
        debit_raw = (row.get("debit") or "").strip()
        if bool(credit_raw) == bool(debit_raw):
            raise InputError(f"Bank statement row {line_no}: exactly one of credit or debit must be populated.")
        is_credit = bool(credit_raw)
        if is_credit:
            amount = _parse_direction_amount(credit_raw, column="credit", ctx=f"row {line_no}")
        else:
            amount = -_parse_direction_amount(debit_raw, column="debit", ctx=f"row {line_no}")
        bank_ref = (row.get(ref_col) or "").strip() if ref_col else None
        vd_raw = (row.get("value_date") or "").strip()
        parsed_date = _parse_date(vd_raw, ctx=f"Bank statement row {line_no}")
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
    # Duplicate keys would break the 1:1 line↔verdict invariant.
    seen: dict[str, int] = {}
    for ln in lines:
        seen[ln.key] = seen.get(ln.key, 0) + 1
    dupes = {k: c for k, c in seen.items() if c > 1}
    if dupes:
        # Identical (date, amount, narration, ref) rows collapse; disambiguate by appending an index.
        counters: dict[str, int] = {}
        fixed: list[BankCreditLine] = []
        for ln in lines:
            if seen[ln.key] > 1:
                counters[ln.key] = counters.get(ln.key, 0) + 1
                newkey = f"{ln.key}#{counters[ln.key]}"
                fixed.append(BankCreditLine(newkey, ln.value_date, ln.amount_paise,
                                            ln.narration, ln.bank_ref, ln.is_credit))
            else:
                fixed.append(ln)
        lines = fixed
    return lines


def load_bank(path: str) -> list[BankCreditLine]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return _load_bank_text(fh, path)
    except FileNotFoundError as exc:
        raise InputError(f"Bank statement not found: {path}. Check the --bank path.") from exc


def load_bank_bytes(content: bytes, source: str = "bank statement") -> list[BankCreditLine]:
    """Parse a caller-owned immutable byte snapshot without reopening a mutable path."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"Bank statement {source} is not valid UTF-8 text.") from exc
    return _load_bank_text(io.StringIO(text, newline=""), source)


def _load_recon_data(data, source: str) -> list[ReconRow]:
    if isinstance(data, dict):
        # Tolerate an envelope {"items": [...]} or {"rows": [...]}.
        for k in ("items", "rows", "recon", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    if not isinstance(data, list):
        raise InputError(
            f"Recon report {source}: expected a JSON array of settled transactions."
        )
    rows: list[ReconRow] = []
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            raise InputError(f"Recon report row {i} is not an object.")
        entity_id = r.get("entity_id")
        rtype = r.get("type")
        if not entity_id or not rtype:
            raise InputError(
                f"Recon report row {i}: missing entity_id/type (the (type, entity_id) join key)."
            )
        rows.append(
            ReconRow(
                entity_id=str(entity_id),
                type=str(rtype),
                amount_paise=_as_int_paise(r.get("amount"), ctx=f"recon row {i} amount"),
                fee_paise=_as_int_paise(r.get("fee"), ctx=f"recon row {i} fee"),
                tax_paise=_as_int_paise(r.get("tax"), ctx=f"recon row {i} tax"),
                debit_paise=_as_int_paise(r.get("debit"), ctx=f"recon row {i} debit"),
                credit_paise=_as_int_paise(r.get("credit"), ctx=f"recon row {i} credit"),
                settlement_id=(str(r["settlement_id"]) if r.get("settlement_id") else None),
                settlement_utr=(str(r["settlement_utr"]) if r.get("settlement_utr") else None),
                settled_at=_epoch_to_dt(r.get("settled_at")),
                created_at=_epoch_to_dt(r.get("created_at")),
                on_hold=bool(r.get("on_hold", False)),
                dispute_id=(str(r["dispute_id"]) if r.get("dispute_id") else None),
                order_id=(str(r["order_id"]) if r.get("order_id") else None),
                method=(str(r["method"]) if r.get("method") else None),
                description=(str(r["description"]) if r.get("description") else None),
                # Vendor-provided IDs are metadata only; physical position is canonical.
                row_id=f"recon_{i}",
            )
        )
    if not rows:
        raise InputError(f"Recon report {source} contained no rows.")
    return rows


def load_recon(path: str) -> list[ReconRow]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise InputError(f"Recon report not found: {path}. Check the --recon path.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InputError(f"Recon report {path} is not valid JSON: {exc}.") from exc
    return _load_recon_data(data, path)


def load_recon_bytes(content: bytes, source: str = "reconciliation report") -> list[ReconRow]:
    """Parse a caller-owned immutable byte snapshot without reopening a mutable path."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise InputError(f"Recon report {source} is not valid JSON: {exc}.") from exc
    return _load_recon_data(data, source)


def _load_ledger_text(fh: Iterable[str], source: str) -> list[OrderLedgerEntry]:
    reader = csv.DictReader(fh)
    fields = set(reader.fieldnames or [])
    if "amount_paise" not in fields:
        raise InputError(
            f"Order ledger {source}: missing required column 'amount_paise'. "
            f"Found: {sorted(fields)}."
        )
    entries: list[OrderLedgerEntry] = []
    for i, row in enumerate(reader, start=2):
        oid = (row.get("order_id") or "").strip() or None
        entries.append(
            OrderLedgerEntry(
                order_id=oid,
                amount_paise=_as_int_paise(row.get("amount_paise"), ctx=f"ledger row {i}"),
                status=(row.get("status") or "").strip(),
                created_at=_parse_dt(row.get("created_at") or ""),
            )
        )
    return entries


def load_ledger(path: str) -> list[OrderLedgerEntry]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return _load_ledger_text(fh, path)
    except FileNotFoundError as exc:
        raise InputError(f"Order ledger not found: {path}. Check the --ledger path.") from exc


def load_ledger_bytes(content: bytes, source: str = "order ledger") -> list[OrderLedgerEntry]:
    """Parse a caller-owned immutable byte snapshot without reopening a mutable path."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"Order ledger {source} is not valid UTF-8 text.") from exc
    return _load_ledger_text(io.StringIO(text, newline=""), source)

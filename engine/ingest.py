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
import io
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from engine.bank_adapters import (
    _BANK_ALIASES,
    _BANK_REQUIRED,
    BankInputProvenance,
    BankLoadResult,
    BankStatementAdapter,
    GenericCsvBankAdapter,
    InputError,
    _line_key,
    _parse_date,
    _parse_direction_amount,
    _rupees_to_paise,
    find_adapter,
    get_default_bank_adapters,
    parse_bank_statement,
)
from engine.models import BankCreditLine, OrderLedgerEntry, ReconRow

__all__ = [
    "BankCreditLine",
    "BankInputProvenance",
    "BankLoadResult",
    "BankStatementAdapter",
    "GenericCsvBankAdapter",
    "InputError",
    "OrderLedgerEntry",
    "ReconRow",
    "_BANK_ALIASES",
    "_BANK_REQUIRED",
    "_line_key",
    "_parse_date",
    "_parse_direction_amount",
    "_rupees_to_paise",
    "find_adapter",
    "get_default_bank_adapters",
    "load_bank",
    "load_bank_bytes",
    "load_bank_bytes_result",
    "load_bank_result",
    "load_ledger",
    "load_ledger_bytes",
    "load_recon",
    "load_recon_bytes",
    "parse_bank_statement",
]



# ---------------------------------------------------------------------------
# Helpers for recon and ledger
# ---------------------------------------------------------------------------


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
    if isinstance(v, bool):
        raise InputError(f"{ctx}: expected an integer paise value, got boolean {v!r}.")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if not v.is_integer():  # also rejects NaN / inf
            raise InputError(f"{ctx}: expected an integer paise value, got non-integer {v!r}.")
        return int(v)
    try:
        return int(str(v).strip())
    except (ValueError, TypeError) as exc:
        raise InputError(f"{ctx}: expected an integer paise value, got {v!r}.") from exc


# ---------------------------------------------------------------------------
# Bank Statement Loaders (Adapter Boundary)
# ---------------------------------------------------------------------------


def load_bank_result(
    path: str,
    *,
    adapters: Sequence[BankStatementAdapter] | None = None,
) -> BankLoadResult:
    """Parse bank statement file and return lines along with immutable adapter provenance."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return parse_bank_statement(fh, source=path, adapters=adapters)
    except FileNotFoundError as exc:
        raise InputError(f"Bank statement not found: {path}. Check the --bank path.") from exc
    except UnicodeDecodeError as exc:
        raise InputError(f"Bank statement {path} is not valid UTF-8 text.") from exc


def load_bank_bytes_result(
    content: bytes,
    source: str = "bank statement",
    *,
    adapters: Sequence[BankStatementAdapter] | None = None,
) -> BankLoadResult:
    """Parse caller-owned immutable byte snapshot and return lines along with adapter provenance."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"Bank statement {source} is not valid UTF-8 text.") from exc
    return parse_bank_statement(io.StringIO(text, newline=""), source=source, adapters=adapters)


def load_bank(path: str) -> list[BankCreditLine]:
    """Parse bank statement file and return canonical list of BankCreditLines."""
    return list(load_bank_result(path).lines)


def load_bank_bytes(content: bytes, source: str = "bank statement") -> list[BankCreditLine]:
    """Parse a caller-owned immutable byte snapshot without reopening a mutable path."""
    return list(load_bank_bytes_result(content, source=source).lines)



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
                authorized_amount_paise=(
                    _as_int_paise(r.get("authorized_amount"), ctx=f"recon row {i} authorized_amount")
                    if r.get("authorized_amount") not in (None, "") else None
                ),
                captured_amount_paise=(
                    _as_int_paise(r.get("captured_amount"), ctx=f"recon row {i} captured_amount")
                    if r.get("captured_amount") not in (None, "") else None
                ),
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
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
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
    except UnicodeDecodeError as exc:
        raise InputError(f"Order ledger {path} is not valid UTF-8 text.") from exc


def load_ledger_bytes(content: bytes, source: str = "order ledger") -> list[OrderLedgerEntry]:
    """Parse a caller-owned immutable byte snapshot without reopening a mutable path."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"Order ledger {source} is not valid UTF-8 text.") from exc
    return _load_ledger_text(io.StringIO(text, newline=""), source)

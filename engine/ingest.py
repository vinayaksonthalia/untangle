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
import json
from datetime import date, datetime

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
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return 0
    try:
        # Bank statements carry rupees with 2 decimals; convert exactly via Decimal-free rounding.
        whole, _, frac = raw.partition(".")
        frac = (frac + "00")[:2]
        sign = -1 if whole.startswith("-") else 1
        whole = whole.lstrip("+-")
        return sign * (int(whole or "0") * 100 + int(frac))
    except ValueError as exc:
        raise InputError(
            f"Bank statement: could not parse amount {raw!r} in {ctx}. "
            f"Expected a rupee value like 12345.67."
        ) from exc


def _parse_date(raw: str, *, ctx: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise InputError(
            f"{ctx}: could not parse date {raw!r}. Expected ISO format YYYY-MM-DD."
        ) from exc


def _epoch_to_dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    try:
        return datetime.fromtimestamp(int(v))
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


def load_bank(path: str) -> list[BankCreditLine]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = set(reader.fieldnames or [])
            missing = _BANK_REQUIRED - fields
            if missing:
                raise InputError(
                    f"Bank statement {path}: missing required column(s) {sorted(missing)}. "
                    f"Found columns: {sorted(fields)}."
                )
            ref_col = "ref_no" if "ref_no" in fields else ("bank_ref" if "bank_ref" in fields else None)
            lines: list[BankCreditLine] = []
            for i, row in enumerate(reader, start=2):
                narration = (row.get("narration") or "").strip()
                credit_raw = (row.get("credit") or "").strip()
                debit_raw = (row.get("debit") or "").strip()
                is_credit = bool(credit_raw)
                if is_credit:
                    amount = _rupees_to_paise(credit_raw, ctx=f"row {i}")
                else:
                    amount = -_rupees_to_paise(debit_raw, ctx=f"row {i}")
                bank_ref = (row.get(ref_col) or "").strip() if ref_col else None
                vd_raw = (row.get("value_date") or "").strip()
                _parse_date(vd_raw, ctx=f"Bank statement row {i}")
                key = _line_key(vd_raw, amount, narration, bank_ref)
                lines.append(
                    BankCreditLine(
                        key=key,
                        value_date=date.fromisoformat(vd_raw),
                        amount_paise=amount,
                        narration=narration,
                        bank_ref=bank_ref or None,
                        is_credit=is_credit,
                    )
                )
    except FileNotFoundError as exc:
        raise InputError(f"Bank statement not found: {path}. Check the --bank path.") from exc
    if not lines:
        raise InputError(f"Bank statement {path} contained no data rows.")
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


def load_recon(path: str) -> list[ReconRow]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise InputError(f"Recon report not found: {path}. Check the --recon path.") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Recon report {path} is not valid JSON: {exc}.") from exc

    if isinstance(data, dict):
        # Tolerate an envelope {"items": [...]} or {"rows": [...]}.
        for k in ("items", "rows", "recon", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    if not isinstance(data, list):
        raise InputError(
            f"Recon report {path}: expected a JSON array of settled transactions."
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
            )
        )
    if not rows:
        raise InputError(f"Recon report {path} contained no rows.")
    return rows


def load_ledger(path: str) -> list[OrderLedgerEntry]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = set(reader.fieldnames or [])
            if "amount_paise" not in fields:
                raise InputError(
                    f"Order ledger {path}: missing required column 'amount_paise'. "
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
    except FileNotFoundError as exc:
        raise InputError(f"Order ledger not found: {path}. Check the --ledger path.") from exc
    return entries

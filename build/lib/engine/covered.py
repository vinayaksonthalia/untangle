"""Exact identity resolution for the settlement rows a reconciliation covers.

A :class:`ReconciliationResult` records the rows it covers twice: ``covered_entity_ids``
(the lossy ``(type, entity_id)`` tuples) and ``covered_row_ids`` (the physical, unambiguous
``recon_<i>`` ids threaded through from :mod:`engine.reconcile`). Every downstream artifact
— fee-GST, proof packets, journal lines, investigation evidence — must be driven from the
*exact* rows that were covered, never a look-alike duplicate.

This module centralises that resolution so the invariant is enforced identically everywhere.
The strict (non-legacy) path fails **closed**: a stale, malformed, or duplicated
``covered_row_ids`` raises rather than silently pricing one entity off another row's numbers.

The canonical row id is ``f"recon_{i}"`` by enumeration order, matching
``SettlementIndex.row_ids`` in :mod:`engine.reconcile`; callers build ``rows_by_id`` the same
way.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from engine.models import ReconciliationResult, ReconRow


def _row_signature(r: ReconRow) -> tuple:
    """The full set of distinguishing fields for a settlement row.

    Two rows that agree on every one of these are genuinely interchangeable — the same fee, tax,
    settlement, dates and flags flow into any accounting artifact regardless of which is chosen —
    so an occurrence counter is enough to tell true duplicates apart. Any *meaningful* difference
    (e.g. two same-``(type, entity_id)`` rows with different fees) yields a different signature and
    therefore a different, position-independent id. The caller-supplied ``row_id`` is deliberately
    excluded: it is untrusted and must never decide physical identity.
    """
    return (
        r.type, r.entity_id, r.amount_paise, r.fee_paise, r.tax_paise, r.debit_paise, r.credit_paise,
        r.settlement_id, r.settlement_utr,
        r.settled_at.isoformat() if r.settled_at else None,
        r.created_at.isoformat() if r.created_at else None,
        r.on_hold, r.dispute_id, r.order_id, r.method, r.description,
    )


def canonical_row_ids(recon_rows: list[ReconRow]) -> dict[int, str]:
    """Map ``id(row) -> stable content-derived canonical id``.

    The id is a hash of the row's distinguishing fields plus an occurrence index among rows with
    an identical signature. Because it is derived from content, not list position, reordering or
    subsetting ``recon_rows`` between reconciliation and any downstream consumer cannot silently
    rebind a covered id to a different physical row — the property a bare ``recon_<position>`` id
    could not guarantee.
    """
    seen: dict[tuple, int] = defaultdict(int)
    out: dict[int, str] = {}
    for r in recon_rows:
        sig = _row_signature(r)
        occ = seen[sig]
        seen[sig] += 1
        # A content fingerprint, not a security digest — usedforsecurity=False says so explicitly.
        digest = hashlib.sha256(repr(sig).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        out[id(r)] = f"row_{digest}_{occ}"
    return out


def rows_by_canonical_id(recon_rows: list[ReconRow]) -> dict[str, ReconRow]:
    """Inverse view ``canonical id -> row`` for downstream resolution.

    Keys are unique by construction (the occurrence index disambiguates identical signatures), and
    the mapping is independent of ``recon_rows`` order for every row that differs meaningfully.
    """
    ids = canonical_row_ids(recon_rows)
    return {ids[id(r)]: r for r in recon_rows}


def resolve_covered_rows_by_id(
    rec: ReconciliationResult,
    rows_by_id: dict[str, ReconRow],
) -> list[ReconRow]:
    """Resolve ``rec``'s covered rows from ``covered_row_ids``, failing closed.

    Precondition: ``rec.covered_row_ids`` is non-empty (the caller handles the legacy,
    row-id-less fallback). Enforces, in order:

    1. **count parity** — one row id per covered entity;
    2. **uniqueness** — no physical row id is reused (a duplicate would count one row twice);
    3. **existence** — every row id resolves to a real row;
    4. **identity** — each resolved row's ``(type, entity_id)`` equals the covered entity tuple
       at the same position, so the rows and the entity list can never drift apart.

    Any violation raises :class:`ValueError`. On success returns the covered rows in
    ``covered_entity_ids`` order.
    """
    row_ids = rec.covered_row_ids
    if len(row_ids) != len(rec.covered_entity_ids):
        raise ValueError(f"{rec.line_key}: covered row identity count does not match covered entities")
    if len(set(row_ids)) != len(row_ids):
        raise ValueError(f"{rec.line_key}: covered row identity contains duplicate row ids")
    rows: list[ReconRow] = []
    for pos, rid in enumerate(row_ids):
        row = rows_by_id.get(rid)
        if row is None:
            raise ValueError(f"{rec.line_key}: covered row {rid!r} is missing")
        expected = tuple(rec.covered_entity_ids[pos])
        if (row.type, row.entity_id) != expected:
            raise ValueError(
                f"{rec.line_key}: covered row {rid!r} resolves to {(row.type, row.entity_id)} "
                f"but covered entity at position {pos} is {expected}"
            )
        rows.append(row)
    return rows

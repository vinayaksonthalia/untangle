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

from engine.models import ReconRow, ReconciliationResult


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

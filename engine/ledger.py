"""Order-ledger reconciliation (Feature 003, spec 003-ledger-reconciliation).

Cross-checks the merchant's order ledger against the PROVEN Razorpay slice and the settlement report,
and returns a small, AGGREGATED class of honest exceptions. Strictly ADDITIVE: a pure function of
already-computed reconciliation outputs plus the ledger — it never feeds back into attribution or
reconciliation, so no verdict and no headline metric changes. Deterministic and read-only.

Design (post sol review):
  - The *reconciled slice* (balanced ReconciliationResults) is the ground truth for "this order's
    money provably arrived in the bank". Discrepancy checks are scoped to it — never to unsettled or
    refund-only report rows, and never to orders the recon report does not attribute to Razorpay.
  - Precision-first: a per-order status/amount conclusion is only drawn when the ledger booking is
    UNAMBIGUOUS (exactly one row for that order). A doubly-booked order is reported ONLY as a
    duplicate; we abstain from a status/amount verdict on it rather than pick an arbitrary row.
  - Amounts are compared to integer paise; formatting is integer-exact (no float).

Reason codes (see specs/003-ledger-reconciliation/contracts/ledger-exceptions.md):
  - ledger_mismatch         — a settled order missing from, or contradicted (status/amount) in, the ledger.
  - duplicate_order_booking — a Razorpay-attributed order_id booked more than once in the ledger.
  - refund_not_reflected    — a settled order with a Razorpay refund/dispute the ledger still marks paid.
"""

from __future__ import annotations

from engine.models import (
    EvidenceItem,
    ExceptionRecord,
    OrderLedgerEntry,
    ReconciliationResult,
    ReconRow,
)

# Recognised ledger status vocabulary (research.md Decision 2), case-insensitive.
_PAID_STATUSES = {"paid", "captured", "settled", "success", "completed"}
_REFUND_STATUSES = {"refunded", "reversed", "chargeback", "disputed", "partially_refunded"}

# Amount agreement tolerance — the same ±₹1 labelled rounding drift reconciliation uses.
_DRIFT_TOLERANCE_PAISE = 100

# How many example order_ids to carry in a summary exception's evidence.
_EXAMPLES = 10


def _inr(paise: int) -> str:
    # Integer-exact formatting — never float division (precision-first).
    neg = paise < 0
    rupees, sub = divmod(abs(paise), 100)
    return f"{'-' if neg else ''}₹{rupees:,}.{sub:02d}"


def _norm(status: str) -> str:
    return (status or "").strip().lower()


def _is_paid(status: str) -> bool:
    return _norm(status) in _PAID_STATUSES


def _is_refund(status: str) -> bool:
    return _norm(status) in _REFUND_STATUSES


def _examples(order_ids: list[str]) -> str:
    ordered = sorted(order_ids)
    head = ordered[:_EXAMPLES]
    more = "" if len(ordered) <= _EXAMPLES else f" … (+{len(ordered) - _EXAMPLES} more)"
    return ", ".join(head) + more


def _evidence(signal: str, order_ids: list[str], extra: list[EvidenceItem] | None = None) -> list[EvidenceItem]:
    """Evidence for an aggregated exception: bounded human examples PLUS the COMPLETE machine-readable
    affected set (never truncated), so downstream consumers can verify/reconcile every affected order."""
    ids = sorted(order_ids)
    ev = [
        EvidenceItem(signal, f"examples: {_examples(ids)}", 0.0),
        EvidenceItem(f"{signal}_all", ";".join(ids), 0.0),  # full set, not capped
    ]
    return ev + (extra or [])


def reconcile_ledger(
    ledger: list[OrderLedgerEntry],
    reconciliations: list[ReconciliationResult],
    recon_rows: list[ReconRow],
) -> list[ExceptionRecord]:
    """Return aggregated ledger-discrepancy exceptions (≤3). Deterministic, additive, read-only.

    Empty/absent ledger (or no order ids to join on) yields an empty list and never raises.
    """
    if not ledger:
        return []

    # --- Indices: derive EVERYTHING from the balanced-covered row slice (sol structural review) ---
    # (type, entity_id) is the recon report's documented unique join key. Be precision-safe even if
    # that invariant were violated: index ALL rows per key, and only use a key that resolves to a
    # single row (or identical duplicates). A key with materially conflicting rows is EXCLUDED from
    # the cross-check (abstain) — never resolve a money conclusion by picking one arbitrary row.
    _rows_by_te: dict[tuple[str, str], list[ReconRow]] = {}
    for r in recon_rows:
        _rows_by_te.setdefault((r.type, r.entity_id), []).append(r)
    # Only a key that resolves to exactly ONE row is used. A repeated (type, entity_id) — which the
    # data model forbids, but ingestion does not reject — is EXCLUDED entirely (abstain), so we never
    # collapse multiplicity that a balanced settlement summed, nor pick an arbitrary row.
    row_by_te: dict[tuple[str, str], ReconRow] = {
        k: rs[0] for k, rs in _rows_by_te.items() if len(rs) == 1
    }
    # Unique (type, entity_id) keys covered by a BALANCED (proven/reconciled) settlement.
    covered_keys: set[tuple[str, str]] = set()
    for rec in reconciliations:
        if rec.balanced:
            covered_keys.update(rec.covered_entity_ids)
    covered_rows = [row_by_te[k] for k in covered_keys if k in row_by_te]

    # "Settled" = an order with a covered PAYMENT row (money provably arrived). Refund-only or
    # dispute-only covered rows do NOT make an order settled and never drive a payment conclusion.
    settled_order_ids: set[str] = set()
    settled_payment_amount: dict[str, int] = {}
    for row in covered_rows:
        if row.order_id and row.type == "payment":
            settled_order_ids.add(row.order_id)
            settled_payment_amount[row.order_id] = settled_payment_amount.get(row.order_id, 0) + row.amount_paise
    # A reconciled refund/dispute, but ONLY for an order that also has a covered payment.
    covered_refund_order_ids: set[str] = {
        row.order_id for row in covered_rows
        if row.order_id and (row.type == "refund" or row.dispute_id) and row.order_id in settled_order_ids
    }

    ledger_by_order: dict[str, list[OrderLedgerEntry]] = {}
    for e in ledger:
        if e.order_id:
            ledger_by_order.setdefault(e.order_id, []).append(e)

    # --- Collect discrepancies, scoped to the PROVEN settled slice ---------------------------
    missing_from_ledger: list[str] = []       # settled, not booked
    status_conflicts: list[str] = []          # settled, single unambiguous booking, wrong status
    amount_conflicts: list[str] = []          # settled, single unambiguous booking, amount off
    duplicates: list[str] = []                # Razorpay-attributed order booked >1×
    refund_unbooked: list[str] = []           # settled refund/dispute, ledger shows no refund

    for oid in settled_order_ids:
        rows = ledger_by_order.get(oid)
        if not rows:
            missing_from_ledger.append(oid)
            continue
        if len(rows) > 1:
            # Ambiguous booking → reported as a duplicate only; abstain on status/amount for it.
            continue
        row = rows[0]
        # Expected ledger state for a settled order: paid; OR a refund status ONLY if the reconciled
        # settlement actually carries a refund/dispute for it. A ledger claiming "refunded" when the
        # report shows no refund is itself a contradiction (sol review MEDIUM).
        status_ok = _is_paid(row.status) or (
            _is_refund(row.status) and oid in covered_refund_order_ids
        )
        if not status_ok:
            status_conflicts.append(oid)
        settled_amt = settled_payment_amount.get(oid)
        if settled_amt is not None and abs(row.amount_paise - settled_amt) > _DRIFT_TOLERANCE_PAISE:
            amount_conflicts.append(oid)

    # Duplicates: a SETTLED order (covered payment) booked more than once in the ledger — scoped to
    # the proven slice, not to any uncovered/unbalanced report row.
    for oid, rows in ledger_by_order.items():
        if len(rows) > 1 and oid in settled_order_ids:
            duplicates.append(oid)

    # refund_not_reflected: a reconciled refund/dispute on a SINGLY-booked settled order whose ledger
    # still shows paid (not refunded). Duplicate-booked orders abstain here too (reported as duplicates).
    for oid in covered_refund_order_ids:
        rows = ledger_by_order.get(oid)
        if rows and len(rows) == 1 and _is_paid(rows[0].status) and not _is_refund(rows[0].status):
            refund_unbooked.append(oid)

    # --- Emit ONE summary exception per non-empty class --------------------------------------
    out: list[ExceptionRecord] = []

    mismatch_bits: list[str] = []
    affected: set[str] = set()
    if missing_from_ledger:
        mismatch_bits.append(f"{len(missing_from_ledger)} settled orders are missing from your ledger")
        affected |= set(missing_from_ledger)
    if status_conflicts:
        mismatch_bits.append(f"{len(status_conflicts)} have a status contradicting a settled payment")
        affected |= set(status_conflicts)
    if amount_conflicts:
        mismatch_bits.append(f"{len(amount_conflicts)} disagree on amount beyond ±₹1")
        affected |= set(amount_conflicts)
    if mismatch_bits:
        out.append(ExceptionRecord(
            line_key="ledger:mismatch",
            reason_code="ledger_mismatch",
            detail=(
                f"{len(affected)} settled orders don't match your ledger — "
                + "; ".join(mismatch_bits) + "."
            ),
            suggested_action="Reconcile these orders in your ledger against the settlement report so the books match.",
            evidence=_evidence("mismatched_orders", list(affected), extra=[
                EvidenceItem("missing_from_ledger", ";".join(sorted(missing_from_ledger)), 0.0),
                EvidenceItem("status_conflicts", ";".join(sorted(status_conflicts)), 0.0),
                EvidenceItem("amount_conflicts", ";".join(sorted(amount_conflicts)), 0.0),
            ]),
        ))

    if duplicates:
        out.append(ExceptionRecord(
            line_key="ledger:duplicate_order_booking",
            reason_code="duplicate_order_booking",
            detail=f"{len(duplicates)} Razorpay-attributed order ids are booked more than once in your ledger.",
            suggested_action="De-duplicate these orders in your ledger; the same order is recorded multiple times.",
            evidence=_evidence("duplicate_orders", duplicates),
        ))

    if refund_unbooked:
        out.append(ExceptionRecord(
            line_key="ledger:refund_not_reflected",
            reason_code="refund_not_reflected",
            detail=f"{len(refund_unbooked)} settled orders have a Razorpay refund or dispute your ledger still marks paid.",
            suggested_action="Record the refunds/disputes against these orders so revenue isn't overstated.",
            evidence=_evidence("unbooked_refunds", refund_unbooked),
        ))

    return out

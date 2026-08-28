"""Recoverable fee-GST from the reconciled Razorpay slice (spec FR-008, US2).

The number is pure EXTRACTION of Razorpay's own itemized ``tax_paise`` (the GST charged on
the processing fee, already inside ``fee_paise``) over the transactions that were reconciled.
No tax is computed from first principles; no eligibility judgment is made. The claim is
merely: "this much GST-on-fee sits inside your reconciled Razorpay credits, itemized per
transaction, so your accountant can see it." Every rupee is traceable to a specific entity_id.
"""

from __future__ import annotations

from collections import defaultdict

from engine.models import FeeGstRecovery, ReconciliationResult, ReconRow


def fee_gst(
    reconciliations: list[ReconciliationResult],
    recon_rows: list[ReconRow],
) -> FeeGstRecovery:
    # Index as a MULTIMAP so duplicate (type, entity_id) rows are not collapsed to the last one —
    # the domain genuinely produces them, and each covered-key occurrence must consume a distinct
    # row (mirrors the journal's Qodo #7 fix; a plain dict here double-counted the surviving row
    # and dropped the shadowed one, so the fee-GST total could disagree with the journal's ITC).
    rows_by_key: dict[tuple[str, str], list[ReconRow]] = defaultdict(list)
    for r in recon_rows:
        rows_by_key[(r.type, r.entity_id)].append(r)

    total = 0
    by_entity: list[tuple[str, int]] = []
    for rec in reconciliations:
        seen: dict[tuple[str, str], int] = defaultdict(int)
        for key in rec.covered_entity_ids:
            k = tuple(key)
            bucket = rows_by_key.get(k, [])
            if seen[k] < len(bucket):
                row = bucket[seen[k]]
                if row.tax_paise:
                    total += row.tax_paise
                    by_entity.append((row.entity_id, row.tax_paise))
            seen[k] += 1
    return FeeGstRecovery(total_recoverable_paise=total, by_entity=by_entity)

"""Recoverable fee-GST from the reconciled Razorpay slice (spec FR-008, US2).

The number is pure EXTRACTION of Razorpay's own itemized ``tax_paise`` (the GST charged on
the processing fee, already inside ``fee_paise``) over the transactions that were reconciled.
No tax is computed from first principles; no eligibility judgment is made. The claim is
merely: "this much GST-on-fee sits inside your reconciled Razorpay credits, itemized per
transaction, so your accountant can see it." Every rupee is traceable to a specific entity_id.
"""

from __future__ import annotations

from engine.models import FeeGstRecovery, ReconciliationResult, ReconRow


def fee_gst(
    reconciliations: list[ReconciliationResult],
    recon_rows: list[ReconRow],
) -> FeeGstRecovery:
    by_id = {(r.type, r.entity_id): r for r in recon_rows}
    total = 0
    by_entity: list[tuple[str, int]] = []
    for rec in reconciliations:
        for key in rec.covered_entity_ids:
            row = by_id.get(tuple(key))
            if row is not None and row.tax_paise:
                total += row.tax_paise
                by_entity.append((row.entity_id, row.tax_paise))
    return FeeGstRecovery(total_recoverable_paise=total, by_entity=by_entity)

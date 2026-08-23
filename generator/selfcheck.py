"""
Conservation self-check. The generator MUST NOT be able to silently emit
ground truth that disagrees with the data it labels.

Invariants asserted:
  I1  For every razorpay_settlement line: true_amount_paise == Σ(credit-debit)
      over its covered_recon_keys (exact, to the paise).
  I2  bank_display_paise == true_amount_paise + rounding_drift_paise (M4 is the
      ONLY permitted discrepancy between the label and the displayed amount).
  I3  Every SETTLED, non-on-hold recon row that belongs to a settlement batch
      is covered by exactly ONE razorpay line (no row lost, none double-counted).
  I4  No on_hold row (settled == False) is ever covered by a bank line (V7).
  I5  Every ground-truth line_id exists in the bank statement, and vice-versa.

Raises AssertionError on any violation; returns a small report dict on success.
"""

from __future__ import annotations

from typing import Dict, List


def run(recon_rows: List[dict], bank_lines: List[dict], truth: List[dict]) -> Dict:
    row_index = {(r["type"], r["entity_id"]): r for r in recon_rows}
    truth_by_id = {t["line_id"]: t for t in truth}
    bank_by_id = {b["line_id"]: b for b in bank_lines}

    # I5: bijection between bank lines and truth labels
    assert set(truth_by_id) == set(bank_by_id), (
        "I5: bank line_ids and ground-truth line_ids do not match "
        f"(bank={len(bank_by_id)}, truth={len(truth_by_id)})"
    )

    coverage_count: Dict[tuple, int] = {}
    checked = 0
    for t in truth:
        if t["rail"] != "razorpay_settlement":
            assert not t["covered_recon_keys"], \
                f"I1: non-razorpay line {t['line_id']} illegally covers recon rows"
            continue
        checked += 1
        s = 0
        for (typ, eid) in t["covered_recon_keys"]:
            r = row_index[(typ, eid)]
            assert not r["on_hold"], f"I4: on_hold row {eid} covered by {t['line_id']}"
            s += r["credit"] - r["debit"]
            coverage_count[(typ, eid)] = coverage_count.get((typ, eid), 0) + 1
        assert s == t["true_amount_paise"], (
            f"I1: line {t['line_id']} sum {s} != true_amount {t['true_amount_paise']}"
        )
        assert t["bank_display_paise"] == t["true_amount_paise"] + t["rounding_drift_paise"], (
            f"I2: line {t['line_id']} display != true + drift"
        )
        assert bank_by_id[t["line_id"]]["credit_paise"] == t["bank_display_paise"], (
            f"I2: bank credit != labeled display for {t['line_id']}"
        )

    # I3: every settled batch row covered exactly once
    settled_batch_rows = [
        (r["type"], r["entity_id"]) for r in recon_rows
        if r["settled"] and r["settlement_id"] is not None
    ]
    missing = [k for k in settled_batch_rows if coverage_count.get(k, 0) == 0]
    doubled = [k for k, c in coverage_count.items() if c > 1]
    assert not missing, f"I3: {len(missing)} settled rows never covered (e.g. {missing[:3]})"
    assert not doubled, f"I3: {len(doubled)} rows double-covered (e.g. {doubled[:3]})"

    return {
        "razorpay_lines_checked": checked,
        "settled_rows_covered": len(settled_batch_rows),
        "invariants": ["I1", "I2", "I3", "I4", "I5"],
        "status": "PASS",
    }

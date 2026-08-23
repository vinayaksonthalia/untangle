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

Adversarial-hardening invariants (FR-016) — the benchmark must actually contain
the cases it claims, so no headline metric rests on an absent hard class:
  I6  Every `brand_less` razorpay line's narration carries NO brand token
      (RAZORPAY / RZPX / RZP) — a brand grep genuinely misses it.
  I7  Every `prefix_destroyed` razorpay line's narration/ref does NOT contain the
      UTR's 10-digit epoch prefix — the UTR can't be recovered from its prefix.
  I8  Every `decoy_brandish` line is a NON-razorpay rail AND carries a brand
      token — a brand grep genuinely false-positives on it.
  I9  Every `amount_collision` razorpay line shares its exact displayed credit
      with at least one non-razorpay bank line — amount is not a key.
  I10 At least one `carry_forward` bank line exists — the case actually fires.

Raises AssertionError on any violation; returns a small report dict on success.
"""

from __future__ import annotations

from typing import Dict, List

BRAND_TOKENS = ("RAZORPAY", "RZPX", "RZP")


def _has_brand(narration: str) -> bool:
    u = (narration or "").upper()
    return any(tok in u for tok in BRAND_TOKENS)


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

    # ---- Adversarial-hardening invariants (I6-I10) ----
    # credit amount -> set of rails that have a bank line with that exact amount
    amount_rails: Dict[int, set] = {}
    for b in bank_lines:
        if b["credit_paise"]:
            amount_rails.setdefault(b["credit_paise"], set()).add(b["_rail"])

    carry_forward_lines = 0
    for t in truth:
        tags = t.get("hard_cases", [])
        narr = bank_by_id[t["line_id"]]["narration"]
        if "carry_forward" in tags:
            carry_forward_lines += 1
        if t["rail"] == "razorpay_settlement":
            if "brand_less" in tags:
                assert not _has_brand(narr), \
                    f"I6: brand_less line {t['line_id']} carries a brand token: {narr!r}"
            if "prefix_destroyed" in tags:
                clean = t.get("bank_leg_utr") or (t["settlement_utrs"][0]
                                                  if t["settlement_utrs"] else "")
                prefix = clean[:10]
                assert prefix and prefix not in narr, (
                    f"I7: prefix_destroyed line {t['line_id']} still exposes UTR "
                    f"prefix {prefix!r} in {narr!r}"
                )
            if "amount_collision" in tags:
                rails = amount_rails.get(t["bank_display_paise"], set())
                assert any(r != "razorpay_settlement" for r in rails), (
                    f"I9: amount_collision line {t['line_id']} has no non-rzp "
                    f"line sharing amount {t['bank_display_paise']}"
                )
        else:
            if "decoy_brandish" in tags:
                assert _has_brand(narr), \
                    f"I8: decoy_brandish line {t['line_id']} lacks a brand token: {narr!r}"

    assert carry_forward_lines >= 1, \
        "I10: no carry_forward bank line was produced (case declared but absent)"

    return {
        "razorpay_lines_checked": checked,
        "settled_rows_covered": len(settled_batch_rows),
        "carry_forward_lines": carry_forward_lines,
        "invariants": ["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10"],
        "status": "PASS",
    }

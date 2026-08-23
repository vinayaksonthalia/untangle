"""
difficulty_probe — adversarial-benchmark proof (FR-016 / SC-003).

Runs three NAIVE single-key baselines against the blind ground truth and prints
precision/recall PER hard-case class. It reads ONLY the generated data files
(data/bank_statement.csv, data/recon_report.json, data/ground_truth.json) — the
same inputs a matcher would see plus the answer key — and imports no generator
internals, so it is a fair external audit.

The three baselines, each a binary "is this bank credit a razorpay_settlement?":
  1. amount-only join   — predict razorpay iff the line's credit equals some
                          per-settlement_id net from the recon report (±7 paise).
  2. brand-keyword grep — predict razorpay iff narration contains RAZORPAY/RZPX/RZP.
  3. clean-UTR join     — predict razorpay iff ref_no is a verbatim recon UTR,
                          or a recon UTR appears verbatim in the narration.

If the benchmark is genuinely adversarial, each baseline stays HIGH on the easy
majority but visibly FAILS on the class it is blind to:
  * brand grep         -> ~0 recall on brand_less; big FP rate on decoy_brandish.
  * clean-UTR join     -> ~0 recall on mangled_utr / prefix_destroyed / utr_absent
                          / split_settlement (legs carry their own bank UTR).
  * amount-only join   -> low recall on split/merge/carry; big FP rate on
                          amount_collision decoys.

Usage:  python -m generator.difficulty_probe [--data data]
Exit code 0 always (read-only report). No wall clock, no randomness.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from typing import Dict, List

BRAND_TOKENS = ("RAZORPAY", "RZPX", "RZP")
DRIFT_TOL = 7  # paise; matches the generator's max rounding-drift magnitude
RZP = "razorpay_settlement"

# razorpay-line tags that define a "hard" line (absence of all => easy majority)
HARD_RZP_TAGS = [
    "brand_less", "mangled_utr", "prefix_destroyed", "utr_absent",
    "amount_collision", "split_settlement", "merge_settlements", "carry_forward",
]
# non-razorpay decoy classes (measured by false-positive rate)
DECOY_TAGS = ["decoy_brandish", "amount_collision"]


def _paise(rupees: str) -> int:
    rupees = (rupees or "").strip()
    if not rupees:
        return 0
    neg = rupees.startswith("-")
    rupees = rupees.lstrip("-")
    whole, _, freac = rupees.partition(".")
    frac = (freac + "00")[:2]
    val = int(whole) * 100 + int(frac)
    return -val if neg else val


def load(data_dir: str):
    with open(os.path.join(data_dir, "ground_truth.json")) as f:
        truth = json.load(f)["labels"]
    truth_by_id = {t["line_id"]: t for t in truth}
    with open(os.path.join(data_dir, "recon_report.json")) as f:
        recon = json.load(f)
    lines: List[dict] = []
    with open(os.path.join(data_dir, "bank_statement.csv")) as f:
        for row in csv.DictReader(f):
            lid = row["line_id"]
            t = truth_by_id[lid]
            lines.append({
                "line_id": lid,
                "narration": row["narration"],
                "ref_no": row["ref_no"],
                "credit": _paise(row["credit"]),
                "rail": t["rail"],
                "tags": t.get("hard_cases", []),
            })
    return lines, recon


# ---- Baselines -----------------------------------------------------------
def baseline_amount(lines, recon):
    nets: Dict[str, int] = {}
    for r in recon:
        sid = r.get("settlement_id")
        if sid is None:
            continue
        nets[sid] = nets.get(sid, 0) + (r["credit"] - r["debit"])
    net_vals = sorted(set(nets.values()))
    pred = {}
    for l in lines:
        c = l["credit"]
        if c <= 0:
            pred[l["line_id"]] = False
            continue
        pred[l["line_id"]] = any(abs(c - v) <= DRIFT_TOL for v in net_vals)
    return pred


def baseline_brand(lines, recon):
    pred = {}
    for l in lines:
        u = l["narration"].upper()
        pred[l["line_id"]] = any(tok in u for tok in BRAND_TOKENS)
    return pred


def baseline_clean_utr(lines, recon):
    utrs = set(r["settlement_utr"] for r in recon if r.get("settlement_utr"))
    pred = {}
    for l in lines:
        ref = l["ref_no"]
        narr = l["narration"]
        hit = ref in utrs or any(u in narr for u in utrs)
        pred[l["line_id"]] = hit
    return pred


# ---- Scoring -------------------------------------------------------------
def pr(lines, pred):
    tp = fp = fn = 0
    for l in lines:
        p = pred[l["line_id"]]
        actual = l["rail"] == RZP
        if p and actual:
            tp += 1
        elif p and not actual:
            fp += 1
        elif (not p) and actual:
            fn += 1
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    return prec, rec, tp, fp, fn


def recall_for(lines, pred, predicate):
    sub = [l for l in lines if predicate(l)]
    if not sub:
        return None, 0
    hit = sum(1 for l in sub if pred[l["line_id"]])
    return hit / len(sub), len(sub)


def main(argv=None):
    ap = argparse.ArgumentParser(description="adversarial difficulty probe")
    ap.add_argument("--data", default="data")
    args = ap.parse_args(argv)

    lines, recon = load(args.data)
    preds = {
        "amount": baseline_amount(lines, recon),
        "brand": baseline_brand(lines, recon),
        "clean_utr": baseline_clean_utr(lines, recon),
    }
    order = ["amount", "brand", "clean_utr"]

    print("=" * 72)
    print("ADVERSARIAL DIFFICULTY PROBE — naive single-key baselines vs truth")
    print(f"data: {args.data}   bank lines: {len(lines)}   "
          f"razorpay lines: {sum(1 for l in lines if l['rail']==RZP)}")
    print("=" * 72)

    # Overall precision/recall
    print("\nOVERALL (positive class = razorpay_settlement)")
    print(f"  {'baseline':<12}{'precision':>11}{'recall':>9}   (tp/fp/fn)")
    for b in order:
        prec, rec, tp, fp, fn = pr(lines, preds[b])
        print(f"  {b:<12}{prec:>10.0%}{rec:>9.0%}   ({tp}/{fp}/{fn})")

    # Per-hard-case RECALL on razorpay lines (should collapse on the blind class)
    def is_easy(l):
        return l["rail"] == RZP and not any(t in l["tags"] for t in HARD_RZP_TAGS)

    rzp_classes = [("easy_majority (rzp, no hard tag)", is_easy)]
    for tag in HARD_RZP_TAGS:
        rzp_classes.append((f"rzp:{tag}",
                            lambda l, tag=tag: l["rail"] == RZP and tag in l["tags"]))

    print("\nRECALL per razorpay hard-case class  (fraction of true rzp lines a")
    print("baseline still labels razorpay — LOW = that key is blind to the class)")
    print(f"  {'class':<38}{'n':>4}" + "".join(f"{b:>11}" for b in order))
    for name, pred_fn in rzp_classes:
        row = f"  {name:<38}"
        n = 0
        cells = []
        for b in order:
            r, n = recall_for(lines, preds[b], pred_fn)
            cells.append("   --   " if r is None else f"{r:>10.0%}")
        row = f"  {name:<38}{n:>4}" + "".join(f"{c:>11}" for c in cells)
        print(row)

    # Per-decoy-class FALSE-POSITIVE rate on non-razorpay lines
    decoy_classes = []
    for tag in DECOY_TAGS:
        decoy_classes.append((f"non-rzp:{tag}",
                              lambda l, tag=tag: l["rail"] != RZP and tag in l["tags"]))

    print("\nFALSE-POSITIVE rate per decoy class  (fraction of these NON-rzp lines")
    print("a baseline WRONGLY labels razorpay — HIGH = that key is fooled)")
    print(f"  {'class':<38}{'n':>4}" + "".join(f"{b:>11}" for b in order))
    for name, pred_fn in decoy_classes:
        cells = []
        n = 0
        for b in order:
            r, n = recall_for(lines, preds[b], pred_fn)  # here "recall" = FP rate
            cells.append("   --   " if r is None else f"{r:>10.0%}")
        print(f"  {name:<38}{n:>4}" + "".join(f"{c:>11}" for c in cells))

    print("\nInterpretation: each baseline is HIGH on the easy majority but visibly")
    print("FAILS on the class it cannot see (recall collapses) and/or is fooled by")
    print("its matching decoy (false positives spike). No single key solves it.")
    print("=" * 72)


if __name__ == "__main__":
    main()

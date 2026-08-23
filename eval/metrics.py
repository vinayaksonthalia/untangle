"""Scoring against BLIND ground truth (spec FR-015). Imported only by eval/.

The engine never imports this module and never reads ground_truth.json. The join
bridges the engine's content-hash ``line_key`` to ground truth's ``line_id`` via the
bank CSV (both are derived from the same rows, in order).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass

from engine.ingest import load_bank

_RAILS = ["razorpay_settlement", "other_gateway", "direct_upi", "cod_remittance", "unrelated"]


def build_key_to_lineid(bank_csv: str) -> dict[str, str]:
    """Map engine line_key -> generator line_id, using CSV row order."""
    lines = load_bank(bank_csv)
    with open(bank_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != len(lines):
        raise ValueError("bank CSV row count != loaded line count")
    mapping: dict[str, str] = {}
    for ln, row in zip(lines, rows, strict=True):
        lid = (row.get("line_id") or "").strip()
        mapping[ln.key] = lid
    return mapping


@dataclass
class PR:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 4), "recall": round(self.recall, 4),
            "support": self.tp + self.fn,
        }


def score(report: dict, truth_path: str, bank_csv: str) -> dict:
    truth = json.load(open(truth_path, encoding="utf-8"))
    labels = {lab["line_id"]: lab for lab in truth["labels"]}
    key2lid = build_key_to_lineid(bank_csv)

    # predicted rail per line_id
    pred: dict[str, tuple[str, float]] = {}
    for a in report["attributions"]:
        lid = key2lid.get(a["line_key"])
        if lid:
            pred[lid] = (a["rail"], a["confidence"])

    # ---- per-rail precision/recall ----
    per_rail = {r: PR() for r in _RAILS}
    for lid, lab in labels.items():
        true_rail = lab["rail"]
        p_rail, _ = pred.get(lid, ("UNKNOWN", 0.0))
        for r in _RAILS:
            if p_rail == r and true_rail == r:
                per_rail[r].tp += 1
            elif p_rail == r and true_rail != r:
                per_rail[r].fp += 1
            elif p_rail != r and true_rail == r:
                per_rail[r].fn += 1

    # ---- per-hard-case recall + razorpay false-positive ----
    hard: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0, "abstained": 0,
                                                 "rzp_fp": 0})
    for lid, lab in labels.items():
        p_rail, _ = pred.get(lid, ("UNKNOWN", 0.0))
        true_rail = lab["rail"]
        for tag in lab.get("hard_cases", []):
            h = hard[tag]
            h["n"] += 1
            if p_rail == true_rail:
                h["correct"] += 1
            if p_rail == "UNKNOWN":
                h["abstained"] += 1
            if p_rail == "razorpay_settlement" and true_rail != "razorpay_settlement":
                h["rzp_fp"] += 1
    per_hard = {}
    for tag, h in sorted(hard.items()):
        per_hard[tag] = {
            "n": h["n"],
            "recall": round(h["correct"] / h["n"], 4) if h["n"] else 0.0,
            "abstain_rate": round(h["abstained"] / h["n"], 4) if h["n"] else 0.0,
            "razorpay_false_positives": h["rzp_fp"],
        }

    # ---- decoy false-positive rate (any non-rzp truth predicted razorpay) ----
    non_rzp_total = sum(1 for lab in labels.values() if lab["rail"] != "razorpay_settlement")
    decoy_fp = sum(
        1 for lid, lab in labels.items()
        if lab["rail"] != "razorpay_settlement" and pred.get(lid, ("UNKNOWN", 0))[0] == "razorpay_settlement"
    )

    # ---- calibration bins ----
    bins = [(i / 10, (i + 1) / 10) for i in range(10)]
    calib = []
    for lo, hi in bins:
        items = [(lid, c) for lid, (r, c) in pred.items()
                 if r != "UNKNOWN" and lo <= c < hi + (1e-9 if hi == 1.0 else 0)]
        if not items:
            continue
        correct = sum(1 for lid, c in items if pred[lid][0] == labels.get(lid, {}).get("rail"))
        mean_conf = sum(c for _, c in items) / len(items)
        calib.append({
            "bin": f"[{lo:.1f},{hi:.1f})", "n": len(items),
            "mean_confidence": round(mean_conf, 4),
            "empirical_accuracy": round(correct / len(items), 4),
        })

    # ---- conservation (MVP subset of data-model invariants) ----
    n_lines = report["totals"]["n_bank_lines"]
    n_verdicts = len(report["attributions"])
    keys = [a["line_key"] for a in report["attributions"]]
    exactly_one = (n_verdicts == n_lines) and (len(set(keys)) == n_verdicts)
    attributed = report["totals"]["attributed"]
    abstained = report["totals"]["abstained"]
    accounts = (attributed + abstained == n_lines)
    conservation = {
        "every_line_exactly_one_verdict": exactly_one,
        "attributed_plus_abstained_equals_total": accounts,
        "pass": exactly_one and accounts,
    }

    # overall (reported alongside per-rail; NEVER as the sole headline)
    overall_correct = sum(1 for lid, lab in labels.items()
                          if pred.get(lid, ("UNKNOWN", 0))[0] == lab["rail"])
    coverage = sum(1 for r, _ in pred.values() if r != "UNKNOWN") / len(labels)

    return {
        "n_labels": len(labels),
        "per_rail": {r: per_rail[r].as_dict() for r in _RAILS},
        "per_hard_case": per_hard,
        "decoy_false_positive": {
            "non_rzp_lines": non_rzp_total,
            "predicted_razorpay": decoy_fp,
            "rate": round(decoy_fp / non_rzp_total, 4) if non_rzp_total else 0.0,
        },
        "calibration": calib,
        "conservation": conservation,
        "overall": {
            "accuracy_incl_abstain": round(overall_correct / len(labels), 4),
            "coverage": round(coverage, 4),
        },
    }

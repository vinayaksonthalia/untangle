"""Scoring against BLIND ground truth (spec FR-015). Imported only by eval/.

The engine never imports this module and never reads ground_truth.json. The join
bridges the engine's content-hash ``line_key`` to ground truth's ``line_id`` via the
bank CSV (both are derived from the same rows, in order).
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field

from engine.ingest import load_bank

_RAILS = ["razorpay_settlement", "other_gateway", "direct_upi", "cod_remittance", "unrelated"]

# Fixed 95% normal quantile.  Wilson intervals are preferable to Wald intervals for
# the small and boundary-heavy samples in this benchmark (including 0/n and n/n).
_Z95 = 1.959963984540054

# Cluster bootstrap parameters. Split settlements emit several correlated bank legs from ONE
# settlement event, so the labelled lines are NOT independent Bernoulli trials — a line-level
# Wilson interval would be too narrow to honestly call "95%". We resample the underlying
# settlement EVENTS (clusters), which propagates that correlation into the interval width. Fixed
# seed + sorted cluster order = deterministic (constitution: reproducible metrics).
_BOOT_SEED = 20260830
_BOOT_RESAMPLES = 5000


def wilson_ci95(successes: int, trials: int) -> tuple[float, float] | None:
    """Return a Wilson score interval for a binomial proportion.

    ``None`` means there is no estimand because the denominator is zero.  The
    interval is deterministic and bounded in [0, 1], including at 0/n and n/n.
    The public evaluator currently exposes only the conventional 95% interval.
    """
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    if trials == 0:
        return None
    n = float(trials)
    p = successes / n
    z2 = _Z95 * _Z95
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = _Z95 * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    low = 0.0 if successes == 0 else max(0.0, centre - half)
    high = 1.0 if successes == trials else min(1.0, centre + half)
    return (low, high)


def format_ci(ci: dict | None) -> str:
    """Render a precision/recall CI dict as ``s/n [low, high]``, or ``unavailable``.

    The CI dict is always present (it carries the point counts), so a zero-denominator interval is
    signalled by ``low``/``high`` being ``None`` — presentation must check the bounds, never the
    dict's truthiness, or it would print the literal ``[None, None]``.
    """
    if not ci or ci.get("low") is None or ci.get("high") is None:
        return "unavailable"
    return f"{ci['successes']}/{ci['trials']} [{ci['low']}, {ci['high']}]"


def _cluster_key(label: dict) -> tuple:
    """The independent-event key for a labelled bank line.

    Split-settlement legs of one event share the same ``settlement_ids`` and so land in one
    cluster; a line with no settlement ids is its own singleton cluster (independent).
    """
    sids = label.get("settlement_ids") or []
    if sids:
        return ("setl", tuple(sorted(sids)))
    return ("line", label["line_id"])


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 100]) of an already-sorted, non-empty list."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (q / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def cluster_bootstrap_ci95(
    cluster_successes: dict[tuple, list[int]],
    *,
    seed: int = _BOOT_SEED,
    resamples: int = _BOOT_RESAMPLES,
) -> tuple[float, float] | None:
    """95% cluster-bootstrap interval for a proportion whose trials are grouped into clusters.

    ``cluster_successes`` maps each cluster key to the list of 0/1 outcomes it contributes to the
    metric's denominator (e.g. for razorpay precision: one entry per predicted-razorpay line, 1 iff
    it was a true positive). Resampling whole clusters — not individual lines — with replacement
    keeps correlated split legs together, so the interval widens to reflect the true, smaller number
    of independent events. Returns ``None`` when the denominator is empty (no estimand).
    """
    clusters = sorted(cluster_successes)  # deterministic order
    total = sum(len(cluster_successes[c]) for c in clusters)
    if total == 0:
        return None
    rng = random.Random(seed)
    n = len(clusters)
    ratios: list[float] = []
    for _ in range(resamples):
        drawn = rng.choices(clusters, k=n)
        num = 0
        den = 0
        for c in drawn:
            outcomes = cluster_successes[c]
            num += sum(outcomes)
            den += len(outcomes)
        if den:
            ratios.append(num / den)
    if not ratios:
        return None
    ratios.sort()
    return (_percentile(ratios, 2.5), _percentile(ratios, 97.5))


def _ci_dict(successes: int, trials: int, cluster_successes: dict[tuple, list[int]]) -> dict:
    """95% interval for a precision/recall proportion, cluster-aware by settlement event.

    ``successes``/``trials`` are retained for continuity of the reported point count; ``low``/``high``
    come from the cluster bootstrap so correlated split legs do not understate uncertainty.
    """
    interval = cluster_bootstrap_ci95(cluster_successes)
    return {
        "successes": successes,
        "trials": trials,
        "low": round(interval[0], 4) if interval else None,
        "high": round(interval[1], 4) if interval else None,
        "method": "cluster_bootstrap",
        "clusters": len(cluster_successes),
        "resamples": _BOOT_RESAMPLES,
    }


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
    # Per-settlement-event outcomes feeding the cluster bootstrap: for this rail, precision's
    # denominator is the predicted-this-rail lines (1 iff true positive); recall's is the truly-
    # this-rail lines (1 iff true positive). Keyed by _cluster_key so split legs group together.
    _prec_clusters: dict[tuple, list[int]] = field(default_factory=lambda: defaultdict(list))
    _rec_clusters: dict[tuple, list[int]] = field(default_factory=lambda: defaultdict(list))

    def record(self, *, predicted: bool, actual: bool, cluster: tuple) -> None:
        tp = predicted and actual
        if predicted:
            self.tp += 1 if tp else 0
            self.fp += 0 if tp else 1
            self._prec_clusters[cluster].append(1 if tp else 0)
        if actual:
            if not predicted:
                self.fn += 1
            self._rec_clusters[cluster].append(1 if tp else 0)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    def as_dict(self) -> dict:
        precision_n = self.tp + self.fp
        recall_n = self.tp + self.fn
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 4), "recall": round(self.recall, 4),
            "support": self.tp + self.fn,
            "precision_ci95": _ci_dict(self.tp, precision_n, dict(self._prec_clusters)),
            "recall_ci95": _ci_dict(self.tp, recall_n, dict(self._rec_clusters)),
        }


def score(report: dict, truth_path: str, bank_csv: str) -> dict:
    truth = json.load(open(truth_path, encoding="utf-8"))
    labels = {lab["line_id"]: lab for lab in truth["labels"]}
    key2lid = build_key_to_lineid(bank_csv)

    # predicted rail per line_id
    pred: dict[str, tuple[str, float]] = {}
    for a in report["attributions"]:
        lid = key2lid.get(a["line_key"])
        assert lid is not None, (
            f"prediction {a['line_key']} has no matching bank line — would silently "
            "convert a false positive into a false negative")
        pred[lid] = (a["rail"], a["confidence"])

    # ---- per-rail precision/recall ----
    per_rail = {r: PR() for r in _RAILS}
    for lid, lab in labels.items():
        true_rail = lab["rail"]
        p_rail, _ = pred.get(lid, ("UNKNOWN", 0.0))
        cluster = _cluster_key(lab)
        for r in _RAILS:
            per_rail[r].record(predicted=(p_rail == r), actual=(true_rail == r), cluster=cluster)

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

    total_calib_n = sum(b["n"] for b in calib)
    ece = (
        sum(b["n"] * abs(b["empirical_accuracy"] - b["mean_confidence"]) for b in calib)
        / total_calib_n
        if total_calib_n
        else 0.0
    )

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

    # ---- precision-at-coverage & abstention curve ----
    threshold_steps = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
    cov_curve = []
    for tau in threshold_steps:
        n_attr = sum(1 for _, (r, c) in pred.items() if r != "UNKNOWN" and c >= tau)
        n_abst = len(labels) - n_attr
        cov = n_attr / len(labels) if labels else 0.0
        abst_rate = n_abst / len(labels) if labels else 0.0
        rzp_tp = sum(
            1 for lid, (r, c) in pred.items()
            if r == "razorpay_settlement" and c >= tau and labels.get(lid, {}).get("rail") == "razorpay_settlement"
        )
        rzp_fp = sum(
            1 for lid, (r, c) in pred.items()
            if r == "razorpay_settlement" and c >= tau and labels.get(lid, {}).get("rail") != "razorpay_settlement"
        )
        rzp_prec = rzp_tp / (rzp_tp + rzp_fp) if (rzp_tp + rzp_fp) else 1.0
        cov_curve.append({
            "threshold": tau,
            "coverage": round(cov, 4),
            "abstention_rate": round(abst_rate, 4),
            "n_attributed": n_attr,
            "n_abstained": n_abst,
            "razorpay_precision": round(rzp_prec, 4),
        })

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
        "ece": round(ece, 4),
        "precision_at_coverage": cov_curve,
        "conservation": conservation,
        "overall": {
            "accuracy_incl_abstain": round(overall_correct / len(labels), 4),
            "coverage": round(coverage, 4),
        },
    }

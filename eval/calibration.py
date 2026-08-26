"""Noisy-OR Reliability Diagram and Calibration (spec §5, ANTIGRAVITY_BUILD_PLAN.md §2 Phase 2).

Computes Expected Calibration Error (ECE) and renders the reliability diagram
(predicted confidence vs observed empirical accuracy) across standard probability bins.
Shows where the abstention threshold sits on the calibrated score.

CLI usage:
    python -m eval.calibration --run out/report.json --truth data/ground_truth.json
"""

from __future__ import annotations

import argparse
import json
import sys

from eval.metrics import build_key_to_lineid, score


def render_reliability_diagram(calib: list[dict], ece: float, threshold: float = 0.55) -> str:
    """Render an ASCII reliability diagram showing calibration curve and abstention threshold."""
    lines: list[str] = []
    lines.append("================================================================================")
    lines.append("                   NOISY-OR RELIABILITY DIAGRAM (CALIBRATION)                   ")
    lines.append("================================================================================")
    status = "PASS" if ece <= 0.10 else "FAIL"
    lines.append(f"Expected Calibration Error (ECE): {ece:.4f}  (Phase 2 Gate: ECE <= 0.10 -> {status})")
    lines.append(f"Abstention Threshold: {threshold:.2f} (credits with confidence < {threshold:.2f} abstain)")
    lines.append("")
    lines.append("Bin         Count   Mean Conf   Empirical Acc   Gap       Reliability Plot (Acc: *, Conf: |, Perfect: .)")
    lines.append("--------------------------------------------------------------------------------")

    width = 30
    for b in calib:
        b_name = b["bin"]
        n = b["n"]
        conf = b["mean_confidence"]
        acc = b["empirical_accuracy"]
        gap = abs(acc - conf)

        # Plot bar of width 30 representing [0.0, 1.0]
        # . represents the center of the bin (ideal diagonal)
        lo_s, hi_s = b_name.strip("[]()").split(",")
        mid = (float(lo_s) + float(hi_s)) / 2.0

        bar = [" "] * (width + 1)
        ideal_pos = min(width, int(mid * width))
        bar[ideal_pos] = "."

        conf_pos = min(width, int(conf * width))
        bar[conf_pos] = "|"

        acc_pos = min(width, int(acc * width))
        bar[acc_pos] = "*" if bar[acc_pos] == " " else "X"

        bar_str = "".join(bar)
        lines.append(f"{b_name:<11} {n:>5}   {conf:>9.3f}   {acc:>13.3f}   {gap:>6.3f}    [{bar_str}]")

    lines.append("--------------------------------------------------------------------------------")
    lines.append("Legend:   * = Observed Empirical Accuracy    | = Predicted Confidence")
    lines.append("          . = Perfect Calibration Diagonal   X = Conf & Acc overlap")
    lines.append("================================================================================")
    return "\n".join(lines)


def run_calibration(
    report_path: str, truth_path: str, bank_csv: str = "data/bank_statement.csv", threshold: float = 0.55
) -> dict:
    report = json.load(open(report_path, encoding="utf-8"))
    m = score(report, truth_path, bank_csv)
    calib = m["calibration"]
    ece = m.get("ece", 0.0)
    diagram = render_reliability_diagram(calib, ece, threshold)
    return {
        "ece": ece,
        "calib_bins": calib,
        "gate_pass": ece <= 0.10,
        "threshold": threshold,
        "diagram_text": diagram,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.calibration")
    p.add_argument("--run", required=True, help="path to out/report.json")
    p.add_argument("--truth", required=True, help="path to data/ground_truth.json")
    p.add_argument("--bank", default="data/bank_statement.csv", help="bank CSV path")
    p.add_argument("--threshold", type=float, default=0.55, help="abstention threshold")
    p.add_argument("--json", action="store_true", help="emit json")
    args = p.parse_args(argv)

    try:
        res = run_calibration(args.run, args.truth, args.bank, args.threshold)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({k: v for k, v in res.items() if k != "diagram_text"}, indent=2))
    else:
        print(res["diagram_text"])

    return 0 if res["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

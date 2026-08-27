"""Phase 2 Acceptance Gate Test (ANTIGRAVITY_BUILD_PLAN.md §2 Phase 2).

Gate requirements:
  1. Noisy-OR reliability diagram: Expected Calibration Error (ECE) <= 0.10.
  2. Set-sum false-match curve: zero forced set-sum picks across candidate-set sizes up to N=200.
  3. Generated from the engine's own output, deterministic and reproducible.
  4. Engine isolation (G7): engine never reads ground truth or generator source.
"""

from __future__ import annotations

from pathlib import Path

from eval.calibration import run_calibration
from eval.setsum_curve import run_setsum_curve_experiment


def test_phase2_calibration_gate():
    """ECE <= 0.10 on the Noisy-OR reliability diagram from engine attributions."""
    report_path = "out/report.json"
    truth_path = "data/ground_truth.json"
    bank_csv = "data/bank_statement.csv"

    res = run_calibration(report_path, truth_path, bank_csv)
    ece = res["ece"]
    assert ece <= 0.10, f"Expected Calibration Error {ece:.4f} > 0.10 (Phase 2 gate failed)"
    assert res["gate_pass"] is True

    # Verify that bins exist and cover the spectrum
    bins = res["calib_bins"]
    assert len(bins) > 0
    # Every bin's empirical accuracy is non-negative and <= 1.0
    for b in bins:
        assert 0.0 <= b["empirical_accuracy"] <= 1.0
        assert 0.0 <= b["mean_confidence"] <= 1.0


def test_phase2_setsum_zero_forced_picks_gate():
    """Zero forced set-sum picks across candidate pool sizes up to N=200."""
    pool_sizes = [10, 20, 30, 40, 50, 75, 100, 125, 150, 175, 200]
    exp = run_setsum_curve_experiment(pool_sizes=pool_sizes, seed=42, num_queries_per_N=50)

    assert exp["gate_pass"] is True
    assert exp["total_engine_forced_picks"] == 0

    for r in exp["results"]:
        N = r["N"]
        assert r["engine_forced_picks"] == 0, f"Engine forced {r['engine_forced_picks']} picks at N={N}!"
        assert r["engine_forced_pick_rate"] == 0.0

        # When N is large (e.g. >= 100), coincidental collisions naturally occur
        # verify that the naive matcher suffers false matches while Untangle abstains
        if N >= 100 and r["ambiguous_cases"] > 0:
            assert r["naive_forced_picks"] > 0, f"Expected naive matcher to force picks at N={N}"
            assert r["engine_abstentions"] == r["ambiguous_cases"]


def test_phase2_engine_isolation_g7():
    """Verify G7: engine code never imports from generator or reads ground truth."""
    engine_dir = Path("engine")
    for py_file in engine_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "import generator" not in text, f"{py_file} imports generator!"
        assert "from generator" not in text, f"{py_file} imports from generator!"
        assert "ground_truth" not in text, f"{py_file} references ground_truth!"

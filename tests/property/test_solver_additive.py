"""Property: Global evidence-constrained reconciliation solver is ADDITIVE, precision-first, and deterministic.

Non-negotiable invariants:
1. ADDITIVITY (flag OFF):
   Building the report with global_solver=False vs default pipeline (two real independent runs,
   no self-comparing deepcopy) produces 100% BYTE-IDENTICAL results across every headline metric,
   attributions, reconciliations, fee_gst, exceptions, and proof packets.
2. PRECISION-FIRST (flag ON):
   With global_solver=True, run through the real pipeline on both seeded dev and sealed holdout.
   Assert:
   - Razorpay precision == 1.000
   - Decoy false-positives == 0
   - Recall >= current baseline (0.911 dev / 0.839 sealed)
   If precision ever drops below 1.000 or recall drops below baseline, the test FAILS.
3. DETERMINISM (flag ON):
   Running with global_solver=True twice on identical inputs produces identical reports.
4. DEFAULT OFF:
   The solver is disabled by default in Config and CLI.
"""

from __future__ import annotations

import json
import os

from engine.attribute import attribute_all
from engine.cli import build_config, build_report
from engine.evidence import ReconIndex
from engine.ingest import load_bank, load_ledger, load_recon
from eval.metrics import score
from eval.sealed import (
    DEFAULT_SEALED_DIR,
    DEFAULT_SEALED_SEED,
    evaluate_sealed,
    generate_sealed_holdout,
)


def _setup_dev_pipeline():
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    order_ledger = load_ledger("data/order_ledger.csv")
    index = ReconIndex(recon_rows)
    return lines, recon_rows, order_ledger, index


def test_solver_off_is_byte_identical_to_default_pipeline():
    """GENUINE additivity: two real builds with flag off vs default must be byte-identical."""
    lines, recon_rows, order_ledger, index = _setup_dev_pipeline()

    # Build 1: Default config (global_solver not passed, defaults to False)
    cfg_default = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42)
    attrs_default = attribute_all(lines, index, cfg_default.threshold)
    rep_default, _ = build_report(cfg_default, lines, recon_rows, index, attrs_default, order_ledger)
    dict_default = rep_default.to_dict()

    # Build 2: Explicit global_solver=False
    cfg_off = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42, global_solver=False)
    attrs_off = attribute_all(lines, index, cfg_off.threshold, global_solver=False)
    rep_off, _ = build_report(cfg_off, lines, recon_rows, index, attrs_off, order_ledger, global_solver=False)
    dict_off = rep_off.to_dict()

    # Assert complete byte-identity across all sections
    assert json.dumps(dict_default, sort_keys=True) == json.dumps(dict_off, sort_keys=True)

    # Explicit section checks
    assert dict_default["totals"] == dict_off["totals"]
    assert dict_default["attributions"] == dict_off["attributions"]
    assert dict_default["reconciliations"] == dict_off["reconciliations"]
    assert dict_default["fee_gst"] == dict_off["fee_gst"]
    assert dict_default["exceptions"] == dict_off["exceptions"]
    assert dict_default["proof_packets"] == dict_off["proof_packets"]
    assert dict_default["recovery_plan"] == dict_off["recovery_plan"]

    # Pin OFF to the documented PRE-feature baseline, so this proves OFF == historical behaviour
    # (not merely that two ways of specifying OFF agree).
    m_off = score(dict_off, "data/ground_truth.json", "data/bank_statement.csv")
    rzp_off = m_off["per_rail"]["razorpay_settlement"]
    assert rzp_off["precision"] == 1.000
    assert rzp_off["recall"] >= 0.911
    assert m_off["decoy_false_positive"]["predicted_razorpay"] == 0
    assert dict_off["totals"]["reconciled_count"] == 91


def test_solver_on_preserves_precision_and_recall_on_dev_and_sealed():
    """With global_solver=True: precision == 1.000, decoy FP == 0, recall >= baseline."""
    lines, recon_rows, order_ledger, index = _setup_dev_pipeline()

    # 1. Dev dataset (seed 42)
    cfg_on = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42, global_solver=True)
    solver_sink: dict = {}
    attrs_on = attribute_all(lines, index, cfg_on.threshold, global_solver=True, solver_result_out=solver_sink)
    rep_on, _ = build_report(
        cfg_on, lines, recon_rows, index, attrs_on, order_ledger,
        global_solver=True, solver_result=solver_sink.get("solver_result"),
    )
    dict_on = rep_on.to_dict()

    dev_metrics = score(dict_on, "data/ground_truth.json", "data/bank_statement.csv")
    rzp_dev = dev_metrics["per_rail"]["razorpay_settlement"]
    decoy_dev = dev_metrics["decoy_false_positive"]

    assert rzp_dev["precision"] == 1.000, f"Dev precision dropped: {rzp_dev['precision']}"
    assert decoy_dev["predicted_razorpay"] == 0, f"Decoy false positives found: {decoy_dev}"
    assert rzp_dev["recall"] >= 0.911, f"Dev recall below baseline: {rzp_dev['recall']} < 0.911"

    # 2. Sealed holdout (seed 1337)
    if not os.path.exists(os.path.join(DEFAULT_SEALED_DIR, "manifest.json")):
        generate_sealed_holdout(DEFAULT_SEALED_SEED, DEFAULT_SEALED_DIR)

    sealed_res_on = evaluate_sealed(
        DEFAULT_SEALED_DIR,
        out_report="out/sealed_solver_on.json",
        global_solver=True,
    )
    rzp_sealed = sealed_res_on["metrics"]["per_rail"]["razorpay_settlement"]
    decoy_sealed = sealed_res_on["metrics"]["decoy_false_positive"]

    assert rzp_sealed["precision"] == 1.000, f"Sealed precision dropped: {rzp_sealed['precision']}"
    assert decoy_sealed["predicted_razorpay"] == 0, f"Sealed decoy false positives found: {decoy_sealed}"
    assert rzp_sealed["recall"] >= 0.857, f"Sealed recall below baseline: {rzp_sealed['recall']} < 0.857"
    assert sealed_res_on["totals"]["reconciled_count"] == 91, f"Sealed reconciled_count != 91: {sealed_res_on['totals']['reconciled_count']}"


def test_solver_on_is_deterministic():
    """Two independent builds with global_solver=True produce byte-identical reports."""
    lines, recon_rows, order_ledger, index = _setup_dev_pipeline()

    cfg1 = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42, global_solver=True)
    sink1: dict = {}
    attrs1 = attribute_all(lines, index, cfg1.threshold, global_solver=True, solver_result_out=sink1)
    rep1, _ = build_report(cfg1, lines, recon_rows, index, attrs1, order_ledger, global_solver=True, solver_result=sink1.get("solver_result"))

    cfg2 = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42, global_solver=True)
    sink2: dict = {}
    attrs2 = attribute_all(lines, index, cfg2.threshold, global_solver=True, solver_result_out=sink2)
    rep2, _ = build_report(cfg2, lines, recon_rows, index, attrs2, order_ledger, global_solver=True, solver_result=sink2.get("solver_result"))

    assert json.dumps(rep1.to_dict(), sort_keys=True) == json.dumps(rep2.to_dict(), sort_keys=True)


def test_solver_flag_defaults_to_false():
    """The solver flag must strictly default to False in Config and CLI."""
    cfg = build_config(no_ai=True, provider=None, model=None, threshold=None, seed=42)
    assert cfg.global_solver is False

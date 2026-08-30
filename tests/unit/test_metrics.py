"""T013 — Eval scoring computes per-rail / per-hard-case P/R, decoy FP, and
calibration correctly on a tiny controlled fixture."""

from __future__ import annotations

import json

import pytest

from engine.ingest import load_bank
from eval.metrics import cluster_bootstrap_ci95, format_ci, score, wilson_ci95
from eval.sealed import _load_dev_metrics, _validated_display_totals

_BANK_CSV = (
    "line_id,value_date,txn_date,narration,ref_no,debit,credit,balance\n"
    "bl_A,2026-06-02,2026-06-02,IMPS/UTR-A/Razorpay/Settlement,UTRA,,1000.00,1000.00\n"
    "bl_B,2026-06-03,2026-06-03,RTGS/PAYU/PAYOUT,PAYU1,,2000.00,3000.00\n"
    "bl_C,2026-06-04,2026-06-04,NEFT-DECOY-RAZORPAY-LOOKALIKE,X1,,3000.00,6000.00\n"
    "bl_D,2026-06-05,2026-06-05,BRANDLESS SETTLEMENT,Y1,,4000.00,10000.00\n"
)


def _write(tmp_path):
    bank = tmp_path / "bank.csv"
    bank.write_text(_BANK_CSV, encoding="utf-8")
    truth = {
        "_meta": {"note": "test"},
        "labels": [
            {"line_id": "bl_A", "rail": "razorpay_settlement", "hard_cases": ["clean"]},
            {"line_id": "bl_B", "rail": "other_gateway", "hard_cases": []},
            {"line_id": "bl_C", "rail": "unrelated", "hard_cases": ["decoy_brandish"]},
            {"line_id": "bl_D", "rail": "razorpay_settlement", "hard_cases": ["brand_less"]},
        ],
    }
    tp = tmp_path / "truth.json"
    tp.write_text(json.dumps(truth), encoding="utf-8")
    return str(bank), str(tp)


def _report_for(bank_csv):
    # Derive the engine keys in CSV order, then assign controlled predictions:
    #   A -> razorpay (correct, high conf)
    #   B -> other_gateway (correct)
    #   C -> razorpay (WRONG: decoy false positive)
    #   D -> UNKNOWN (abstained; a razorpay recall miss)
    lines = load_bank(bank_csv)
    preds = [
        ("razorpay_settlement", 0.95),
        ("other_gateway", 0.85),
        ("razorpay_settlement", 0.80),
        ("UNKNOWN", 0.0),
    ]
    attrs = [{"line_key": ln.key, "rail": r, "confidence": c, "tier": "B",
              "abstained": r == "UNKNOWN", "llm_used": False, "evidence": []}
             for ln, (r, c) in zip(lines, preds, strict=True)]
    return {"totals": {"n_bank_lines": 4, "attributed": 3, "abstained": 1},
            "attributions": attrs}


def test_per_rail_precision_recall(tmp_path):
    bank, truth = _write(tmp_path)
    m = score(_report_for(bank), truth, bank)
    rzp = m["per_rail"]["razorpay_settlement"]
    assert rzp["tp"] == 1 and rzp["fp"] == 1 and rzp["fn"] == 1
    assert rzp["precision"] == 0.5 and rzp["recall"] == 0.5
    og = m["per_rail"]["other_gateway"]
    assert og["tp"] == 1 and og["precision"] == 1.0 and og["recall"] == 1.0
    assert rzp["precision_ci95"]["successes"] == 1
    assert rzp["precision_ci95"]["trials"] == 2
    assert rzp["precision_ci95"]["method"] == "cluster_bootstrap"
    assert 0.0 <= rzp["precision_ci95"]["low"] <= rzp["precision_ci95"]["high"] <= 1.0


def test_cluster_bootstrap_widens_interval_for_correlated_legs():
    # Identical 6 correct / 4 wrong outcomes (point estimate 0.6 either way). As 10 independent lines
    # the interval is narrow; grouped into 5 two-leg settlement events whose legs share an outcome
    # (3 all-correct events, 2 all-wrong), there are only 5 independent, internally-correlated units,
    # so the honest interval is wider. Counting the legs as independent — the bug Qodo #34 flagged —
    # would understate that uncertainty.
    singletons = {("line", str(i)): [1 if i < 6 else 0] for i in range(10)}
    clustered = {("setl", (str(i),)): ([1, 1] if i < 3 else [0, 0]) for i in range(5)}
    lo_s, hi_s = cluster_bootstrap_ci95(singletons)
    lo_c, hi_c = cluster_bootstrap_ci95(clustered)
    assert (hi_c - lo_c) > (hi_s - lo_s)


def test_cluster_bootstrap_deterministic_and_unavailable_on_empty():
    d = {("setl", ("a",)): [1, 0], ("line", "x"): [1]}
    assert cluster_bootstrap_ci95(d) == cluster_bootstrap_ci95(d)  # fixed seed => reproducible
    assert cluster_bootstrap_ci95({}) is None                      # no clusters => no estimand
    assert cluster_bootstrap_ci95({("line", "x"): []}) is None     # zero denominator => unavailable


def test_wilson_ci_boundaries_and_empty_denominator():
    assert wilson_ci95(0, 0) is None
    assert wilson_ci95(0, 10)[0] == 0.0
    assert wilson_ci95(10, 10)[1] == 1.0
    for successes in range(11):
        low, high = wilson_ci95(successes, 10)
        assert 0.0 <= low <= high <= 1.0


def test_wilson_ci_is_deterministic_and_validates_counts():
    assert wilson_ci95(5, 10) == wilson_ci95(5, 10)
    with pytest.raises(ValueError):
        wilson_ci95(11, 10)
    with pytest.raises(ValueError):
        wilson_ci95(-1, 10)
    with pytest.raises(ValueError):
        wilson_ci95(0, -1)


def test_missing_or_malformed_dev_report_is_unavailable(tmp_path):
    assert _load_dev_metrics(str(tmp_path / "missing.json")) is None
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json", encoding="utf-8")
    assert _load_dev_metrics(str(malformed)) is None


def test_format_ci_renders_unavailable_for_zero_denominator():
    # A zero-denominator interval carries the counts but None bounds — it must never print [None, None].
    assert format_ci({"successes": 0, "trials": 0, "low": None, "high": None}) == "unavailable"
    assert format_ci(None) == "unavailable"
    assert format_ci({"successes": 3, "trials": 4, "low": 0.1, "high": 0.9}) == "3/4 [0.1, 0.9]"


def test_malformed_display_totals_rejected():
    # A present-but-non-integer display total must raise so the caller marks the dev baseline wholly
    # unavailable, rather than reaching f-string arithmetic and crashing the sealed comparison.
    assert _validated_display_totals({"n_bank_lines": 4, "reconciled_count": 3}) == {
        "n_bank_lines": 4, "reconciled_count": 3}
    for bad in ({"fee_gst_recoverable_paise": "lots"},
                {"n_bank_lines": 4.5},
                {"reconciled_count": True},  # bool is not an accepted integer here
                "not-a-dict"):
        with pytest.raises(TypeError):
            _validated_display_totals(bad)
    # Counts and paise cannot be negative — reject rather than display a nonsensical baseline.
    for neg in ({"n_bank_lines": -1}, {"fee_gst_recoverable_paise": -100}):
        with pytest.raises(ValueError):
            _validated_display_totals(neg)


def test_decoy_false_positive_counted(tmp_path):
    bank, truth = _write(tmp_path)
    m = score(_report_for(bank), truth, bank)
    d = m["decoy_false_positive"]
    assert d["predicted_razorpay"] == 1          # bl_C
    assert d["non_rzp_lines"] == 2               # bl_B, bl_C


def test_per_hard_case_and_calibration(tmp_path):
    bank, truth = _write(tmp_path)
    m = score(_report_for(bank), truth, bank)
    # brand_less line D abstained -> recall 0 on that hard case
    assert m["per_hard_case"]["brand_less"]["recall"] == 0.0
    assert m["per_hard_case"]["brand_less"]["abstain_rate"] == 1.0
    # decoy_brandish line C predicted razorpay wrongly
    assert m["per_hard_case"]["decoy_brandish"]["razorpay_false_positives"] == 1
    # calibration: highest bin holds bl_A (correct)
    top = [b for b in m["calibration"] if b["bin"] == "[0.9,1.0)"]
    assert top and top[0]["empirical_accuracy"] == 1.0
    assert m["conservation"]["pass"] is True


def test_sealed_manifest_verification_binds_to_committed_anchor(tmp_path):
    # The frozen holdout must pass; every tamper — an artifact edit, a SELF-CONSISTENT artifact+manifest
    # edit, a wrong seed, or a missing manifest — must fail closed against the committed anchor so a
    # modified benchmark is never scored as the frozen holdout (Qodo full-tree #4 + #44 review).
    import hashlib
    import shutil

    from eval.sealed import (
        DEFAULT_SEALED_SEED,
        SealedIntegrityError,
        _verify_sealed_manifest,
        generate_sealed_holdout,
    )

    # Hermetic: build the frozen seed-1337 holdout here (not the gitignored data/sealed), so the test
    # passes from a clean checkout via `make test` without CI's separate generation step (Qodo #44).
    src = str(tmp_path / "frozen")
    generate_sealed_holdout(DEFAULT_SEALED_SEED, src)
    _verify_sealed_manifest(src)  # intact frozen holdout matches the committed anchor -> no raise

    # (a) Artifact edited, manifest untouched -> per-file hash mismatch.
    d1 = tmp_path / "edited"
    shutil.copytree(src, d1)
    (d1 / "bank_statement.csv").write_text("TAMPERED", encoding="utf-8")
    with pytest.raises(SealedIntegrityError):
        _verify_sealed_manifest(str(d1))

    # (b) Artifact AND its manifest hash edited to stay self-consistent -> the committed files-digest
    #     anchor catches it (this is the case a beside-the-artifacts manifest could not defend).
    d2 = tmp_path / "self_consistent"
    shutil.copytree(src, d2)
    (d2 / "bank_statement.csv").write_text("TAMPERED", encoding="utf-8")
    man = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["bank_statement.csv"] = hashlib.sha256(b"TAMPERED").hexdigest()
    (d2 / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(SealedIntegrityError):
        _verify_sealed_manifest(str(d2))

    # (c) Wrong seed and (d) missing manifest.
    d3 = tmp_path / "wrong_seed"
    shutil.copytree(src, d3)
    man = json.loads((d3 / "manifest.json").read_text(encoding="utf-8"))
    man["seed"] = 999
    (d3 / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(SealedIntegrityError):
        _verify_sealed_manifest(str(d3))
    empty = tmp_path / "no_manifest"
    empty.mkdir()
    with pytest.raises(SealedIntegrityError):
        _verify_sealed_manifest(str(empty))


def test_run_sealed_rejects_non_frozen_seed_before_generating(tmp_path):
    # A non-frozen seed must be rejected UP FRONT (return 2) without generating a holdout, rather than
    # generating one that verification then rejects (Qodo #44 review).
    from eval.sealed import DEFAULT_SEALED_SEED, run_sealed_holdout_comparison

    target = tmp_path / "should_not_exist"
    rc = run_sealed_holdout_comparison(seed=DEFAULT_SEALED_SEED + 1, sealed_dir=str(target))
    assert rc == 2
    assert not target.exists()  # rejected before any generation


def test_sealed_manifest_rejects_non_regular_artifacts_without_raw_os_errors(tmp_path):
    import os
    import shutil

    from eval.sealed import (
        DEFAULT_SEALED_SEED,
        SealedIntegrityError,
        _verify_sealed_manifest,
        generate_sealed_holdout,
    )

    frozen = tmp_path / "frozen"
    generate_sealed_holdout(DEFAULT_SEALED_SEED, str(frozen))

    directory_case = tmp_path / "directory_case"
    shutil.copytree(frozen, directory_case)
    artifact = directory_case / "bank_statement.csv"
    artifact.unlink()
    artifact.mkdir()
    with pytest.raises(SealedIntegrityError, match="not a regular file"):
        _verify_sealed_manifest(str(directory_case))

    if hasattr(os, "mkfifo"):
        fifo_case = tmp_path / "fifo_case"
        shutil.copytree(frozen, fifo_case)
        fifo = fifo_case / "bank_statement.csv"
        fifo.unlink()
        os.mkfifo(fifo)
        with pytest.raises(SealedIntegrityError, match="not a regular file"):
            _verify_sealed_manifest(str(fifo_case))

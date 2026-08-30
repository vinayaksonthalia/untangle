"""T013 — Eval scoring computes per-rail / per-hard-case P/R, decoy FP, and
calibration correctly on a tiny controlled fixture."""

from __future__ import annotations

import json

import pytest

from engine.ingest import load_bank
from eval.metrics import score, wilson_ci95
from eval.sealed import _load_dev_metrics

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
    assert 0.0 <= rzp["precision_ci95"]["low"] <= rzp["precision_ci95"]["high"] <= 1.0


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

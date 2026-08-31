"""Tests preventing bank-format overclaims and enforcing evidence-truth alignment.

Verifies:
1. `eval.sealed` and `eval.harness` CLI outputs do NOT claim four-bank validation.
2. `eval.sealed` and `eval.harness` state the accurate generic/synthetic scope boundary.
3. `get_default_bank_adapters()` registers only the generic CSV adapter.
4. Named banks (HDFC, ICICI, SBI, Axis, Kotak, RBL) are not mislabeled as dedicated-adapter validated.
5. Documentation remains consistent with production adapter registration.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from engine.bank_adapters import GenericCsvBankAdapter, get_default_bank_adapters
from eval.harness import _print_report
from eval.sealed import run_sealed_holdout_comparison


def test_eval_sealed_output_disclaims_named_bank_validation():
    """`eval.sealed` must NOT claim four-bank validation and must state generic/synthetic scope."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = run_sealed_holdout_comparison(seed=1337, sealed_dir="data/sealed")
    assert exit_code == 0
    output = buf.getvalue()

    # Must NOT contain the old unsupported overclaims
    assert "4 primary Indian core-banking formats" not in output
    assert "Validated against 4 primary" not in output
    assert "Validated on 4 primary" not in output

    # Must contain the accurate scope limitation
    assert "Bank ingestion scope: validated on Untangle's generic CSV schema" in output
    assert "Named-bank native export compatibility requires separately evidenced adapters" in output


def test_eval_harness_output_disclaims_named_bank_validation():
    """`eval.harness._print_report` must NOT claim four-bank validation."""
    dummy_metrics = {
        "n_labels": 10,
        "overall": {"accuracy_incl_abstain": 0.9, "coverage": 0.9},
        "per_rail": {
            "razorpay_settlement": {
                "precision": 1.0,
                "recall": 0.9,
                "f1": 0.95,
                "precision_ci95": {"low": 0.95, "high": 1.0, "successes": 5, "trials": 5},
                "recall_ci95": {"low": 0.85, "high": 0.95, "successes": 5, "trials": 5},
                "support": 5,
                "tp": 5,
                "fp": 0,
                "fn": 0,
            }
        },
        "per_hard_case": {},
        "decoy_false_positive": {"predicted_razorpay": 0, "non_rzp_lines": 5, "rate": 0.0},
        "ece": 0.05,
        "calibration": [],
        "conservation": {
            "pass": True,
            "every_line_exactly_one_verdict": True,
            "attributed_plus_abstained_equals_total": True,
        },
    }

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_report(dummy_metrics)
    output = buf.getvalue()


    assert "4 primary Indian core-banking formats" not in output
    assert "Validated against 4 primary" not in output
    assert "Validated on 4 primary" not in output
    assert "Bank ingestion scope: validated on Untangle's generic CSV schema" in output
    assert "Named-bank native export compatibility requires separately evidenced adapters" in output


def test_default_registry_has_only_generic_csv_adapter():
    """`get_default_bank_adapters()` must contain only `GenericCsvBankAdapter`."""
    adapters = get_default_bank_adapters()
    assert len(adapters) == 1
    assert isinstance(adapters[0], GenericCsvBankAdapter)
    assert adapters[0].adapter_id == "generic_csv"
    assert adapters[0].adapter_version == "1.0.0"


def test_bank_format_evidence_matrix_status():
    """`docs/BANK_FORMAT_EVIDENCE.md` must classify named banks accurately."""
    matrix_file = Path("docs/BANK_FORMAT_EVIDENCE.md")
    assert matrix_file.exists(), "docs/BANK_FORMAT_EVIDENCE.md must exist"
    text = matrix_file.read_text(encoding="utf-8")

    # Generic CSV is validated
    assert "generic_csv" in text
    assert "Generic Untangle CSV" in text

    # Named banks must be Level 2 (Narration represented), with no registered adapter.
    named_banks = ["HDFC Bank", "ICICI Bank", "State Bank of India (SBI)", "Axis Bank", "Kotak Mahindra Bank", "RBL Bank"]
    matrix_rows = {
        cells[0].removeprefix("**").removesuffix("**"): cells
        for line in text.splitlines()
        if line.startswith("|")
        if len(cells := [cell.strip() for cell in line.strip("|").split("|")]) >= 4
    }
    for bank in named_banks:
        assert bank in matrix_rows, f"{bank} must be present in evidence matrix"
        row = matrix_rows[bank]
        assert row[2] == "**Level 2: Narration represented**", f"{bank} support level is overstated"
        assert row[3] == "None", f"{bank} must not claim a registered adapter"


def test_docs_do_not_claim_unsupported_bank_adapters():
    """Core documentation files must not claim dedicated bank adapters exist today."""
    for doc_path in ["docs/INPUT_FORMATS.md", "docs/ARCHITECTURE.md", "README.md"]:
        text = Path(doc_path).read_text(encoding="utf-8")
        assert "4 primary Indian core-banking formats" not in text
        assert "universal bank parsing" not in text.lower()

"""Phase 3 Acceptance Gate Test (ANTIGRAVITY_BUILD_PLAN.md §2 Phase 3).

Gate requirements:
  1. Reconcile ONLY the proven-Razorpay slice (never an abstained credit), keyed on settlement_id.
  2. The proven slice balances to the paise (tolerance 0 on exact, residual surfaced on drift).
  3. Recoverable ITC total equals summed GST-on-fee over the proven slice, each rupee traceable.
  4. Zero abstained credits appear in reconciliation.
  5. Unbalanced sets surface a residual; NO balancing entry is ever forced.
  6. FR-016 duplicate/partial cases surface as exceptions (never netted to force a balance).
  7. Verified on both the pinned sample and the full 294-line benchmark.
  8. G7 engine isolation preserved (engine never reads ground truth).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from engine.attribute import attribute_all
from engine.config import DEFAULT_THRESHOLD
from engine.evidence import ReconIndex
from engine.exceptions import build_exceptions
from engine.feegst import fee_gst
from engine.ingest import load_bank, load_recon
from engine.models import BankCreditLine, Rail, ReconRow
from engine.reconcile import _DRIFT_TOLERANCE_PAISE, SettlementIndex, reconcile
from tests.integration.test_phase1_gate import _make_pinned_20_rows, _make_recon_rows


def test_phase3_gate_on_pinned_sample():
    """Verify all Phase 3 gate conditions on the pinned sample."""
    recon_rows = _make_recon_rows()
    index = ReconIndex(recon_rows)
    sample = _make_pinned_20_rows()
    lines = [line for line, _ in sample]
    lines_by_key = {l.key: l for l in lines}

    # 1. Attribute lines
    attributions = attribute_all(lines, index, threshold=DEFAULT_THRESHOLD)

    # 2. Reconcile
    results, unresolved, sidx = reconcile(lines_by_key, attributions, recon_rows)

    # Gate Condition 4: Zero abstained credits appear in reconciliation
    abstained_keys = {a.line_key for a in attributions if a.abstained}
    reconciled_keys = {r.line_key for r in results}
    assert abstained_keys.isdisjoint(reconciled_keys), "Abstained credit found in reconciliation!"

    # Gate Condition 1: Reconcile ONLY the proven-Razorpay slice
    proven_rzp_keys = {
        a.line_key for a in attributions
        if a.rail == Rail.RAZORPAY_SETTLEMENT.value and not a.abstained
    }
    # In pinned sample: 3 Tier A (k_01, k_02, k_03) + 2 Tier C unique setsum (k_04, k_05) = 5 proven
    assert proven_rzp_keys == {"k_01", "k_02", "k_03", "k_04", "k_05"}
    assert reconciled_keys == proven_rzp_keys
    assert len(unresolved) == 0

    # Gate Condition 2: Proven slice balances to the exact paise (tolerance 0)
    for r in results:
        assert r.residual_paise == 0, f"Line {r.line_key} had non-zero residual {r.residual_paise}!"
        assert r.covered_net_paise == r.credit_amount_paise
        assert r.balanced is True

    # Gate Condition 3: Recoverable ITC total equals summed GST-on-fee and is traceable
    recovery = fee_gst(results, recon_rows)
    assert recovery.total_recoverable_paise > 0
    # Every rupee traceable to an entity
    traced_sum = sum(t for _, t in recovery.by_entity)
    assert traced_sum == recovery.total_recoverable_paise
    # 3 Tier A settlements each have tax_paise=30; 2 unique setsums have 2 settlements each (4*30=120)
    # Total = 3*30 + 4*30 = 210 paise
    assert recovery.total_recoverable_paise == 210
    assert len(recovery.by_entity) == 7


def test_phase3_gate_fr016_duplicate_partial_unbalanced():
    """Verify FR-016: duplicate, partial, and unbalanced settlements surface as exceptions."""
    base_date = date(2026, 6, 10)
    rows = [
        ReconRow(
            entity_id="pay_dup", type="payment", amount_paise=100200, fee_paise=200, tax_paise=30,
            debit_paise=0, credit_paise=100000, settlement_id="setl_dup",
            settlement_utr="1780498800dup001",
            settled_at=datetime.combine(base_date, datetime.min.time()),
            created_at=datetime(2026, 6, 1), on_hold=False, dispute_id=None,
            order_id="ord_dup", method="upi", description="dup test",
        ),
        ReconRow(
            entity_id="pay_partial", type="payment", amount_paise=200200, fee_paise=200, tax_paise=30,
            debit_paise=0, credit_paise=200000, settlement_id="setl_part",
            settlement_utr="1780498800prt001",
            settled_at=datetime.combine(base_date, datetime.min.time()),
            created_at=datetime(2026, 6, 1), on_hold=False, dispute_id=None,
            order_id="ord_part", method="upi", description="part test",
        ),
        ReconRow(
            entity_id="pay_unbal", type="payment", amount_paise=300200, fee_paise=200, tax_paise=30,
            debit_paise=0, credit_paise=300000, settlement_id="setl_unbal",
            settlement_utr="1780498800unb001",
            settled_at=datetime.combine(base_date, datetime.min.time()),
            created_at=datetime(2026, 6, 1), on_hold=False, dispute_id=None,
            order_id="ord_unbal", method="upi", description="unbal test",
        ),
        # Uncredited settlement: exists in recon report but never credited in bank
        ReconRow(
            entity_id="pay_uncred", type="payment", amount_paise=400200, fee_paise=200, tax_paise=30,
            debit_paise=0, credit_paise=400000, settlement_id="setl_uncred",
            settlement_utr="1780498800unc001",
            settled_at=datetime.combine(base_date, datetime.min.time()),
            created_at=datetime(2026, 6, 1), on_hold=False, dispute_id=None,
            order_id="ord_uncred", method="upi", description="uncred test",
        ),
    ]

    # Test bank lines:
    # 1 & 2: Duplicate payouts pointing to the SAME settlement UTR (setl_dup)
    # 3: Partial payout (credit is 150,000 paise against 200,000 paise settlement net)
    # 4: Unbalanced credit (credit is 350,000 paise against 300,000 paise settlement net)
    lines = [
        BankCreditLine("line_dup_1", base_date, 100000, "RAZORPAY 1780498800dup001", "1780498800dup001", True),
        BankCreditLine("line_dup_2", base_date, 100000, "RAZORPAY 1780498800dup001", "1780498800dup001", True),
        BankCreditLine("line_part", base_date, 150000, "RAZORPAY 1780498800prt001", "1780498800prt001", True),
        BankCreditLine("line_unbal", base_date, 350000, "RAZORPAY 1780498800unb001", "1780498800unb001", True),
    ]
    lines_by_key = {l.key: l for l in lines}
    index = ReconIndex(rows)
    attrs = attribute_all(lines, index, threshold=DEFAULT_THRESHOLD)

    results, unresolved, sidx = reconcile(lines_by_key, attrs, rows)

    # NONE of these may be force-matched or netted together!
    assert len(results) == 0, "No invalid/duplicate/partial line may be force-matched!"
    assert set(unresolved) == {"line_dup_1", "line_dup_2", "line_part", "line_unbal"}

    # Check that duplicate lines were detected
    assert "line_dup_1" in sidx.duplicate_or_split_lines
    assert "line_dup_2" in sidx.duplicate_or_split_lines
    assert "line_part" in sidx.duplicate_or_split_lines
    assert "line_unbal" in sidx.unbalanced_lines
    assert "setl_uncred" in sidx.uncredited_sids

    # Generate exceptions and verify reason codes
    exc = build_exceptions(
        attrs, unresolved, lines_by_key,
        ambiguous_rzp=sidx.ambiguous_lines,
        duplicate_or_split_rzp=sidx.duplicate_or_split_lines,
        unbalanced_rzp=sidx.unbalanced_lines,
    )
    exc_by_key = {e.line_key: e for e in exc}

    # Duplicate settlement
    assert exc_by_key["line_dup_1"].reason_code == "partial_or_duplicate_settlement"
    assert exc_by_key["line_dup_2"].reason_code == "partial_or_duplicate_settlement"
    assert "split across multiple" in exc_by_key["line_dup_1"].detail

    # Partial settlement
    assert exc_by_key["line_part"].reason_code == "partial_or_duplicate_settlement"

    # Unbalanced residual
    assert exc_by_key["line_unbal"].reason_code == "unbalanced_residual"
    assert "unbalanced reconciliation" in exc_by_key["line_unbal"].detail


def test_phase3_gate_on_benchmark_294_lines():
    """Verify all Phase 3 gate conditions on the full 294-line benchmark."""
    lines = load_bank("data/bank_statement.csv")
    recon_rows = load_recon("data/recon_report.json")
    lines_by_key = {l.key: l for l in lines}
    index = ReconIndex(recon_rows)

    attributions = attribute_all(lines, index, threshold=DEFAULT_THRESHOLD)
    results, unresolved, sidx = reconcile(lines_by_key, attributions, recon_rows)

    # 1. Zero abstained credits appear in reconciliation
    abstained_keys = {a.line_key for a in attributions if a.abstained}
    reconciled_keys = {r.line_key for r in results}
    assert abstained_keys.isdisjoint(reconciled_keys)

    # 2. Partition: exactly 91 reconciled, 18 unresolved out of 109 attributed Razorpay.
    # Split reconstruction (INCIDENTS 006) lifts split-settlement legs back to razorpay_settlement
    # via a PROVABLE unique tie (their amounts uniquely sum to a real settlement net), so recall
    # rises to 0.982 — above even the old guessing recall — with precision still 1.000. Those 16
    # legs are attributed but not yet entity-level reconciled (the per-credit reconcile model can't
    # net a group), so they show as 'reconstructed_split_leg' unresolved. Reconciled slice (91) and
    # recoverable ITC are unchanged. Partition still holds: 91 reconciled + 18 unresolved = 109.
    assert len(results) == 91
    assert len(unresolved) == 18
    rzp_keys = {a.line_key for a in attributions if a.rail == Rail.RAZORPAY_SETTLEMENT.value and not a.abstained}
    assert reconciled_keys | set(unresolved) == rzp_keys
    assert reconciled_keys.isdisjoint(set(unresolved))

    # 3. Exact paise conservation for all reconciled credits
    for r in results:
        assert abs(r.residual_paise) <= _DRIFT_TOLERANCE_PAISE
        assert r.covered_net_paise + r.residual_paise == r.credit_amount_paise
        assert r.balanced is True

    # 4. Recoverable ITC
    recovery = fee_gst(results, recon_rows)
    assert recovery.total_recoverable_paise == 4320099  # ₹43,200.99 exact paise
    assert sum(t for _, t in recovery.by_entity) == recovery.total_recoverable_paise
    assert len(recovery.by_entity) > 0


def test_phase3_engine_isolation_g7():
    """Verify G7: engine code never imports from generator or reads ground truth."""
    engine_dir = Path("engine")
    for py_file in engine_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "import generator" not in text, f"{py_file} imports generator!"
        assert "from generator" not in text, f"{py_file} imports from generator!"
        assert "ground_truth" not in text, f"{py_file} references ground_truth!"

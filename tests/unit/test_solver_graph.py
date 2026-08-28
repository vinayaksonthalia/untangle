"""Unit tests for Phase 1: Candidate graph construction (engine/solver.py).

Tests written FIRST [test-first]:
- The critical proof-gate invariant: NO edge from a credit to a razorpay_settlement
  node may be created for brand-only, IFSC-only, or unlisted settlement_ref tokens.
- Exact UTR ties and unique amount correlations create proof-valid Razorpay edges.
- Non-Razorpay rail narration patterns create respective rail edges.
- Every credit node has an abstain sink edge.
- Provable split-groups create multi-credit split candidate edges.
- Oversized candidate pools (> _SPLIT_MAX_CANDIDATES = 60) are bounded and marked un-enumerable (abstain).
- Connected component partitioning and determinism.
"""

from __future__ import annotations

from datetime import date, datetime

from engine.attribute import _SPLIT_MAX_CANDIDATES, attribute_all
from engine.evidence import ReconIndex
from engine.models import BankCreditLine, Rail, ReconRow
from engine.solver import build_candidate_graph


def _line(
    key: str,
    narr: str = "x",
    ref: str | None = None,
    amount: int = 100000,
    vd: str = "2026-06-10",
) -> BankCreditLine:
    return BankCreditLine(
        key=key,
        value_date=date.fromisoformat(vd),
        amount_paise=amount,
        narration=narr,
        bank_ref=ref,
        is_credit=True,
    )


def _empty_index() -> ReconIndex:
    return ReconIndex([])


def _index_with_settlement(
    sid: str,
    utr: str,
    net: int = 100000,
    dt: date = date(2026, 6, 10),
) -> ReconIndex:
    row = ReconRow(
        entity_id=f"pay_{sid}",
        type="payment",
        amount_paise=net,
        fee_paise=0,
        tax_paise=0,
        debit_paise=0,
        credit_paise=net,
        settlement_id=sid,
        settlement_utr=utr,
        settled_at=datetime.combine(dt, datetime.min.time()),
        created_at=datetime.combine(dt, datetime.min.time()),
        on_hold=False,
        dispute_id=None,
        order_id=None,
        method="upi",
        description=None,
    )
    return ReconIndex([row])


def test_proof_gate_invariant_no_razorpay_edge_for_brand_only():
    """CRITICAL: A credit with a Razorpay brand word but NO settlement tie must NEVER create a Razorpay edge."""
    line = _line("k_brand", narr="NEFT-RAZORPAY SOFTWARE PVT LTD-TRANSFER", amount=50000)
    idx = _empty_index()
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    assert "k_brand" in graph.credits
    candidates = graph.candidates_by_credit["k_brand"]
    rzp_candidates = [c for c in candidates if c.rail == Rail.RAZORPAY_SETTLEMENT.value]
    assert len(rzp_candidates) == 0, (
        f"Proof-gate violated: brand-only credit received Razorpay candidate edges: {rzp_candidates}"
    )


def test_proof_gate_invariant_no_razorpay_edge_for_ifsc_only():
    """CRITICAL: A credit with the Razorpay RATN IFSC but NO settlement tie must NEVER create a Razorpay edge."""
    line = _line("k_ifsc", narr="RTGS-RATN0000088-SETTLEMENT PAY", amount=250000)
    idx = _empty_index()
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    candidates = graph.candidates_by_credit["k_ifsc"]
    rzp_candidates = [c for c in candidates if c.rail == Rail.RAZORPAY_SETTLEMENT.value]
    assert len(rzp_candidates) == 0, (
        f"Proof-gate violated: IFSC-only credit received Razorpay candidate edges: {rzp_candidates}"
    )


def test_proof_gate_invariant_no_razorpay_edge_for_unlisted_settlement_ref():
    """CRITICAL: Brand word + an unlisted 16-char UTR token is resemblance, not proof — must NOT create Razorpay edge."""
    line = _line("k_unlisted", narr="RAZORPAY 1780498800xp8vma SETTLEMENT", amount=350000)
    idx = _empty_index()  # token is NOT in the recon report
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    candidates = graph.candidates_by_credit["k_unlisted"]
    rzp_candidates = [c for c in candidates if c.rail == Rail.RAZORPAY_SETTLEMENT.value]
    assert len(rzp_candidates) == 0, (
        f"Proof-gate violated: unlisted settlement_ref received Razorpay candidate edges: {rzp_candidates}"
    )


def test_exact_utr_creates_razorpay_edge():
    """A clean verified UTR in recon index creates a proof-valid Tier A Razorpay settlement candidate edge."""
    utr = "1780498800xp8vma"
    line = _line("k_utr", narr=f"NEFT-{utr}-RAZORPAY", amount=150000)
    idx = _index_with_settlement("setl_01", utr=utr, net=150000)
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    candidates = graph.candidates_by_credit["k_utr"]
    rzp_candidates = [c for c in candidates if c.rail == Rail.RAZORPAY_SETTLEMENT.value]
    assert len(rzp_candidates) >= 1
    exact_cand = rzp_candidates[0]
    assert exact_cand.target_id == "setl_01"
    assert exact_cand.tier == "A"
    assert any(e.signal == "utr_exact" for e in exact_cand.evidence)
    assert exact_cand.cost_tuple[0] == 0  # 0 invalid constraint picks


def test_unique_amount_corr_creates_razorpay_edge():
    """A credit whose amount uniquely matches a settlement net in date window creates a Razorpay candidate edge."""
    line = _line("k_amt", narr="TRANSFER REF 999", amount=123456, vd="2026-06-10")
    idx = _index_with_settlement("setl_amt", utr="UTRUNRELATED", net=123456, dt=date(2026, 6, 10))
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    candidates = graph.candidates_by_credit["k_amt"]
    rzp_candidates = [c for c in candidates if c.rail == Rail.RAZORPAY_SETTLEMENT.value]
    assert len(rzp_candidates) >= 1
    assert any(c.target_id == "setl_amt" for c in rzp_candidates)


def test_non_razorpay_rail_edges():
    """Distinctive narration patterns for other rails create valid non-Razorpay rail candidate edges."""
    line_upi = _line("k_upi", narr="UPI/CR/123456789012/JOHN DOE PAYMENT", amount=5000)
    line_cod = _line("k_cod", narr="BLUEDART COD REMITTANCE 888", amount=25000)
    line_gw = _line("k_gw", narr="PAYU PAYMENTS PRIVATE LIMITED", amount=75000)

    lines = [line_upi, line_cod, line_gw]
    idx = _empty_index()
    attrs = attribute_all(lines, idx, 0.55)

    graph = build_candidate_graph(lines, idx, attrs)

    upi_cands = [c for c in graph.candidates_by_credit["k_upi"] if c.rail == Rail.DIRECT_UPI.value]
    assert len(upi_cands) >= 1

    cod_cands = [c for c in graph.candidates_by_credit["k_cod"] if c.rail == Rail.COD_REMITTANCE.value]
    assert len(cod_cands) >= 1

    gw_cands = [c for c in graph.candidates_by_credit["k_gw"] if c.rail == Rail.OTHER_GATEWAY.value]
    assert len(gw_cands) >= 1


def test_abstain_sink_always_present():
    """Every credit node in the graph must have an abstain sink candidate edge."""
    line = _line("k1", narr="RANDOM NARRATION", amount=10000)
    idx = _empty_index()
    attrs = attribute_all([line], idx, 0.55)

    graph = build_candidate_graph([line], idx, attrs)

    cands = graph.candidates_by_credit["k1"]
    abstain_cands = [c for c in cands if c.target_id == "abstain" and c.rail == Rail.UNKNOWN.value]
    assert len(abstain_cands) == 1
    assert abstain_cands[0].cost_tuple[1] == 10000  # unexplained paise = credit amount


def test_provable_split_group_creates_split_candidate():
    """Two credits summing to a settlement net with a strong Razorpay signal produce a split candidate edge."""
    # Leg 1: carries RATN IFSC (strong Razorpay signal)
    l1 = _line("k_leg1", narr="RTGS-RATN0000088-SPLIT1", amount=40000, vd="2026-06-10")
    # Leg 2: carries brand word (Razorpay-leaning)
    l2 = _line("k_leg2", narr="RAZORPAY SETTLEMENT SPLIT2", amount=60000, vd="2026-06-11")

    # Settlement net: 100,000
    idx = _index_with_settlement("setl_split", utr="UTR_SPLIT_PARENT", net=100000, dt=date(2026, 6, 10))
    attrs = attribute_all([l1, l2], idx, 0.55)

    graph = build_candidate_graph([l1, l2], idx, attrs)

    split_cands = [c for c in graph.candidates if c.is_split and c.target_id == "setl_split"]
    assert len(split_cands) == 1
    cand = split_cands[0]
    assert set(cand.credit_keys) == {"k_leg1", "k_leg2"}
    assert cand.residual_paise == 0
    assert cand.rail == Rail.RAZORPAY_SETTLEMENT.value
    assert cand.tier == "C"


def test_oversized_candidate_pool_bounded_by_split_max_candidates():
    """Pools with > _SPLIT_MAX_CANDIDATES (60) are marked un-enumerable and do not generate split edges."""
    lines = []
    # Create 65 credits eligible for split summing
    for i in range(_SPLIT_MAX_CANDIDATES + 5):
        lines.append(
            _line(f"k_bulk_{i:02d}", narr="RATN0000088 SPLIT", amount=1000, vd="2026-06-10")
        )
    idx = _index_with_settlement("setl_large", utr="UTR_LARGE", net=2000, dt=date(2026, 6, 10))
    attrs = attribute_all(lines, idx, 0.55)

    graph = build_candidate_graph(lines, idx, attrs)

    # All 65 credits must be marked as un_enumerable
    for ln in lines:
        assert ln.key in graph.un_enumerable_credits

    # No split edge for setl_large may be created
    split_cands = [c for c in graph.candidates if c.is_split and c.target_id == "setl_large"]
    assert len(split_cands) == 0


def test_connected_components_partitioning():
    """Competing credits share a component; independent credits form isolated components."""
    # Credit 1 and Credit 2 both have candidate edges to Settlement S1
    l1 = _line("k1", narr="TRANSFER 1", amount=100000, vd="2026-06-10")
    l2 = _line("k2", narr="TRANSFER 2", amount=100000, vd="2026-06-10")

    # Credit 3 has an exact UTR to Settlement S2
    l3 = _line("k3", narr="NEFT-UTR_S2-RAZORPAY", amount=50000, vd="2026-06-10")

    row1 = ReconRow(
        entity_id="pay_s1", type="payment", amount_paise=100000, fee_paise=0, tax_paise=0,
        debit_paise=0, credit_paise=100000, settlement_id="s1", settlement_utr="UTR_S1",
        settled_at=datetime(2026, 6, 10), created_at=datetime(2026, 6, 10), on_hold=False,
        dispute_id=None, order_id=None, method="upi", description=None,
    )
    row2 = ReconRow(
        entity_id="pay_s2", type="payment", amount_paise=50000, fee_paise=0, tax_paise=0,
        debit_paise=0, credit_paise=50000, settlement_id="s2", settlement_utr="UTR_S2",
        settled_at=datetime(2026, 6, 10), created_at=datetime(2026, 6, 10), on_hold=False,
        dispute_id=None, order_id=None, method="upi", description=None,
    )
    idx = ReconIndex([row1, row2])
    lines = [l1, l2, l3]
    attrs = attribute_all(lines, idx, 0.55)

    graph = build_candidate_graph(lines, idx, attrs)

    # Find components containing k1, k2, k3
    comp_map = {}
    for comp in graph.components:
        for k in comp:
            comp_map[k] = comp

    assert comp_map["k1"] == comp_map["k2"], "k1 and k2 compete for s1 and must be in the same component"
    assert "k3" not in comp_map["k1"], "k3 is independent and must not share component with k1/k2"
    assert comp_map["k3"] == ["k3"], "k3 should be in an isolated single-node component"


def test_graph_determinism():
    """Running build_candidate_graph multiple times produces identical node IDs and candidate edges."""
    l1 = _line("k1", narr="RAZORPAY 1780498800xp8vma", amount=150000)
    l2 = _line("k2", narr="UPI-123456789012-JOHN", amount=50000)
    idx = _index_with_settlement("setl_1", utr="1780498800xp8vma", net=150000)
    lines = [l1, l2]
    attrs = attribute_all(lines, idx, 0.55)

    g1 = build_candidate_graph(lines, idx, attrs)
    g2 = build_candidate_graph(lines, idx, attrs)

    assert [c.assignment_id for c in g1.candidates] == [c.assignment_id for c in g2.candidates]
    assert g1.components == g2.components
    assert list(g1.credits.keys()) == list(g2.credits.keys())
    assert [c.cost_tuple for c in g1.candidates] == [c.cost_tuple for c in g2.candidates]

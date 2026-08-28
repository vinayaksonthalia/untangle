"""Global evidence-constrained reconciliation solver (Feature 006).

Formulates whole-period reconciliation as a single constrained assignment problem
over a bounded bipartite/multilayer candidate graph. Reconciles globally consistent
assignments and rejects local matches that no globally valid solution can support.

Constitutional constraints:
- Deterministic, stdlib-only (no scipy, pulp, or networkx; no LLM).
- Gated behind a flag (default-OFF); byte-identical to baseline when OFF.
- Proof-gate precondition: NO edge to razorpay_settlement without a proof tie
  (_RZP_TIE_SIGNALS or provable subset-sum). Brand words/IFSC alone NEVER create an edge.
- Bounded candidate pool (_SPLIT_MAX_CANDIDATES); oversized pools fail-closed to abstain.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from engine.attribute import (
    _RZP_LEANING_SIGNALS,
    _RZP_TIE_SIGNALS,
    _SPLIT_CONFIDENCE,
    _SPLIT_DATE_WINDOW,
    _SPLIT_DRIFT_PAISE,
    _SPLIT_MAX_CANDIDATES,
    _SPLIT_MAX_LEGS,
    _STRONG_RZP_SIGNALS,
    _all_sum_subsets,
    _combine,
)
from engine.evidence import (
    ReconIndex,
    extract_utr_tokens,
    narration_rail_signals,
    razorpay_signals,
)
from engine.models import BankCreditLine, EvidenceItem, Rail, RailAttribution, Tier


@dataclass(frozen=True)
class SolverNode:
    """A node in the assignment graph (credit, settlement, rail, or abstain sink)."""

    node_id: str
    kind: str  # "credit", "settlement", "rail", "abstain"
    amount_paise: int
    value_date: date | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateAssignment:
    """An edge representing one possible way to resolve one or more credits."""

    assignment_id: str
    credit_keys: tuple[str, ...]
    target_id: str
    rail: str
    tier: str
    confidence: float
    evidence: tuple[EvidenceItem, ...]
    residual_paise: int
    cost_tuple: tuple[int, int, int, float, float]
    is_split: bool = False


@dataclass
class AssignmentGraph:
    """Bounded candidate assignment graph for one period."""

    credits: dict[str, SolverNode]
    settlements: dict[str, SolverNode]
    candidates: list[CandidateAssignment]
    candidates_by_credit: dict[str, list[CandidateAssignment]]
    candidates_by_settlement: dict[str, list[CandidateAssignment]]
    components: list[list[str]]
    un_enumerable_credits: set[str]


def build_candidate_graph(
    lines: list[BankCreditLine],
    index: ReconIndex,
    attributions: list[RailAttribution] | None = None,
    *,
    max_candidates: int = _SPLIT_MAX_CANDIDATES,
) -> AssignmentGraph:
    """Construct bounded candidate assignment graph for one period.

    Pure function:
    - Left nodes: BankCreditLine instances.
    - Right nodes: settlement net amounts and non-Razorpay terminal rails.
    - Edges: only proof-valid candidate assignments. For Razorpay, an edge
      MUST carry a tie in _RZP_TIE_SIGNALS or be part of a provable subset-sum.
    - Connected components: partitions credits into independent solvable clusters.
    - Bounded: components exceeding max_candidates combinations are marked un-enumerable.
    """
    credit_nodes: dict[str, SolverNode] = {}
    for ln in lines:
        if ln.is_credit and ln.amount_paise > 0:
            credit_nodes[ln.key] = SolverNode(
                node_id=ln.key,
                kind="credit",
                amount_paise=ln.amount_paise,
                value_date=ln.value_date,
                metadata={"narration": ln.narration, "bank_ref": ln.bank_ref},
            )

    settlement_nodes: dict[str, SolverNode] = {}
    for sid, net in sorted(index.settlement_net.items()):
        settlement_nodes[sid] = SolverNode(
            node_id=sid,
            kind="settlement",
            amount_paise=net,
            value_date=index.settlement_date.get(sid),
        )

    candidates: list[CandidateAssignment] = []
    un_enumerable_credits: set[str] = set()

    # 1. Generate single-credit candidate edges
    for ln in lines:
        if not (ln.is_credit and ln.amount_paise > 0):
            continue

        # (a) Abstain sink edge (always available)
        abstain_cost = (0, ln.amount_paise, 0, 0.0, 2.0)
        candidates.append(
            CandidateAssignment(
                assignment_id=f"{ln.key}->abstain",
                credit_keys=(ln.key,),
                target_id="abstain",
                rail=Rail.UNKNOWN.value,
                tier=Tier.B.value,
                confidence=0.0,
                evidence=(),
                residual_paise=0,
                cost_tuple=abstain_cost,
                is_split=False,
            )
        )

        # (b) Non-Razorpay rail candidate edges
        rail_evs = narration_rail_signals(ln)
        for rail_obj, items in sorted(rail_evs.items(), key=lambda kv: kv[0].value if hasattr(kv[0], "value") else str(kv[0])):
            rail_name = rail_obj.value if hasattr(rail_obj, "value") else str(rail_obj)
            score = _combine(items)
            if score > 0.0:
                cost = (0, 0, 0, -round(score, 4), 0.5)
                candidates.append(
                    CandidateAssignment(
                        assignment_id=f"{ln.key}->rail:{rail_name}",
                        credit_keys=(ln.key,),
                        target_id=f"rail:{rail_name}",
                        rail=rail_name,
                        tier=Tier.B.value,
                        confidence=round(score, 4),
                        evidence=tuple(items),
                        residual_paise=0,
                        cost_tuple=cost,
                        is_split=False,
                    )
                )

        # (c) Razorpay single-credit settlement edges
        # HARD PROOF-GATE: an edge to razorpay_settlement may ONLY be created when
        # the credit carries a genuine tie in _RZP_TIE_SIGNALS.
        rzp_ev = razorpay_signals(ln, index)
        tie_signals = {e.signal for e in rzp_ev if e.signal in _RZP_TIE_SIGNALS}

        if tie_signals:
            matched_sids: set[str] = set()

            # Exact UTR tie
            if "utr_exact" in tie_signals:
                utr_tokens = extract_utr_tokens(ln.narration)
                if ln.bank_ref:
                    utr_tokens.append(ln.bank_ref.strip())
                for tok in utr_tokens:
                    tok_clean = tok.lower()
                    if index.utr_exact(tok_clean):
                        sid = index.utr_to_sid.get(tok_clean)
                        if sid:
                            matched_sids.add(sid)

            # Corroborated UTR suffix tie
            if "utr_suffix" in tie_signals:
                for e in rzp_ev:
                    if e.signal == "utr_suffix":
                        # Token tails settlement_utr; extract matching sid
                        for tok in extract_utr_tokens(ln.narration):
                            u = index.utr_suffix_match(tok)
                            if u:
                                sid = index.utr_to_sid.get(u.lower())
                                if sid:
                                    matched_sids.add(sid)

            # Unique amount correlation tie
            if "amount_corr" in tie_signals:
                sids = index.net_to_settlements.get(ln.amount_paise, [])
                for sid in sids:
                    sdate = index.settlement_date.get(sid)
                    if sdate is not None and abs((ln.value_date - sdate).days) <= _SPLIT_DATE_WINDOW:
                        matched_sids.add(sid)

            # Build candidate assignment for each verified settlement tie
            for sid in sorted(matched_sids):
                net = index.settlement_net.get(sid, ln.amount_paise)
                residual = ln.amount_paise - net
                is_exact = "utr_exact" in tie_signals
                tier = Tier.A.value if is_exact else Tier.B.value
                conf = 0.95 if is_exact else _combine(rzp_ev)
                cost = (
                    0,
                    0,
                    abs(residual),
                    -round(conf, 4),
                    0.0 if is_exact else 1.0,
                )
                candidates.append(
                    CandidateAssignment(
                        assignment_id=f"{ln.key}->{sid}",
                        credit_keys=(ln.key,),
                        target_id=sid,
                        rail=Rail.RAZORPAY_SETTLEMENT.value,
                        tier=tier,
                        confidence=round(conf, 4),
                        evidence=tuple(rzp_ev),
                        residual_paise=residual,
                        cost_tuple=cost,
                        is_split=False,
                    )
                )

    # 2. Generate multi-credit split candidate edges
    # Eligible credits: credit > 0, no competing rail keyword, carries Razorpay-leaning signal
    sig_by_key: dict[str, set[str]] = {}
    split_candidates: list[BankCreditLine] = []
    for ln in lines:
        if not (ln.is_credit and ln.amount_paise > 0 and not narration_rail_signals(ln)):
            continue
        sigs = {e.signal for e in razorpay_signals(ln, index)}
        if _RZP_LEANING_SIGNALS & sigs:
            split_candidates.append(ln)
            sig_by_key[ln.key] = sigs

    for sid in sorted(index.settlement_net):
        net = index.settlement_net[sid]
        sdate = index.settlement_date.get(sid)
        if net <= 0 or sdate is None:
            continue

        elig = [
            c for c in split_candidates
            if c.amount_paise < net and abs((c.value_date - sdate).days) <= _SPLIT_DATE_WINDOW
        ]
        if len(elig) < 2:
            continue

        if len(elig) > max_candidates:
            un_enumerable_credits.update(c.key for c in elig)
            continue

        for sub in _all_sum_subsets(elig, net, _SPLIT_DRIFT_PAISE, _SPLIT_MAX_LEGS):
            # Must carry at least one strong Razorpay signal (IFSC RATN or verified UTR suffix)
            if not any(_STRONG_RZP_SIGNALS & sig_by_key[c.key] for c in sub):
                continue
            if any(c.key in un_enumerable_credits for c in sub):
                continue

            sub_keys = tuple(sorted(c.key for c in sub))
            residual = sum(c.amount_paise for c in sub) - net
            cost = (0, 0, abs(residual), -_SPLIT_CONFIDENCE, 1.5)
            candidates.append(
                CandidateAssignment(
                    assignment_id=f"split:{sid}:{'+'.join(sub_keys)}",
                    credit_keys=sub_keys,
                    target_id=sid,
                    rail=Rail.RAZORPAY_SETTLEMENT.value,
                    tier=Tier.C.value,
                    confidence=_SPLIT_CONFIDENCE,
                    evidence=(),
                    residual_paise=residual,
                    cost_tuple=cost,
                    is_split=True,
                )
            )

    # Sort candidates deterministically
    candidates.sort(key=lambda c: (c.credit_keys, c.target_id, c.assignment_id))

    # Map candidates by credit and by settlement
    candidates_by_credit: dict[str, list[CandidateAssignment]] = defaultdict(list)
    candidates_by_settlement: dict[str, list[CandidateAssignment]] = defaultdict(list)
    for c in candidates:
        for k in c.credit_keys:
            candidates_by_credit[k].append(c)
        if c.target_id in settlement_nodes:
            candidates_by_settlement[c.target_id].append(c)

    # 3. Partition into connected components
    # Credits are linked if they appear in the same multi-leg edge or compete for the same settlement
    adj: dict[str, set[str]] = defaultdict(set)
    for k in credit_nodes:
        adj[k] = set()

    for _sid, s_cands in candidates_by_settlement.items():
        all_keys = sorted({k for c in s_cands for k in c.credit_keys})
        for i in range(len(all_keys)):
            for j in range(i + 1, len(all_keys)):
                adj[all_keys[i]].add(all_keys[j])
                adj[all_keys[j]].add(all_keys[i])

    visited: set[str] = set()
    components: list[list[str]] = []
    for k in sorted(credit_nodes.keys()):
        if k in visited:
            continue
        comp: list[str] = []
        queue = deque([k])
        visited.add(k)
        while queue:
            curr = queue.popleft()
            comp.append(curr)
            for neighbor in sorted(adj[curr]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        comp.sort()
        components.append(comp)

    components.sort(key=lambda c: (len(c), c[0]))

    return AssignmentGraph(
        credits=credit_nodes,
        settlements=settlement_nodes,
        candidates=candidates,
        candidates_by_credit=dict(candidates_by_credit),
        candidates_by_settlement=dict(candidates_by_settlement),
        components=components,
        un_enumerable_credits=un_enumerable_credits,
    )

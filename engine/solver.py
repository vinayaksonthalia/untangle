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

import re
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
from engine.config import DEFAULT_THRESHOLD
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


@dataclass(frozen=True)
class CreditAssignmentVerdict:
    """Final assignment verdict for a single bank credit."""

    line_key: str
    rail: str
    target_id: str
    confidence: float
    tier: str
    evidence: tuple[EvidenceItem, ...]
    abstained: bool
    residual_paise: int = 0
    covered_split_keys: tuple[str, ...] = ()
    competing_global_explanation: dict[str, Any] | None = None
    rejected_local_matches: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SolverResult:
    """Full period reconciliation solution from the global solver."""

    verdicts: dict[str, CreditAssignmentVerdict]
    consumed_settlements: set[str]
    objective_cost: tuple[int, int, int, float, float]
    rejected_matches: list[dict[str, Any]]
    is_optimal: bool = True
    note: str | None = None


_MAX_SPLIT_COMBINATIONS = 50000
_MAX_BRANCH_STEPS = 10000


def build_candidate_graph(
    lines: list[BankCreditLine],
    index: ReconIndex,
    attributions: list[RailAttribution] | None = None,
    *,
    max_candidates: int = _SPLIT_MAX_CANDIDATES,
    max_combinations: int = _MAX_SPLIT_COMBINATIONS,
    threshold: float | None = None,
) -> AssignmentGraph:
    """Construct bounded candidate assignment graph for one period.

    Pure function:
    - Left nodes: BankCreditLine instances.
    - Right nodes: settlement net amounts and non-Razorpay terminal rails.
    - Edges: only proof-valid candidate assignments. For Razorpay, an edge
      MUST carry a tie in _RZP_TIE_SIGNALS or be part of a provable subset-sum.
    - Connected components: partitions credits into independent solvable clusters.
    - Bounded: components exceeding max_candidates or max_combinations are marked un-enumerable.
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
            if threshold is not None and score < threshold:
                continue
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
                        # Token tails settlement_utr; extract matching sid from detail or index
                        m = re.search(r"settlement_utr\s+([a-z0-9]+)", e.detail, re.I)
                        if m:
                            sid = index.utr_to_sid.get(m.group(1).lower())
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
                # A tied Razorpay edge is proof (the proof-gate already validated the tie), so at the
                # default threshold it is always kept. Only a STRICTER-than-default run additionally
                # requires the confidence to clear that stricter bar (Qodo #3: single edges below
                # threshold should not be emitted on elevated-threshold runs).
                if threshold is not None and threshold > DEFAULT_THRESHOLD and conf < threshold:
                    continue
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
    # Guard: if split confidence is below the runtime threshold, splits abstain (Bug 3)
    if threshold is None or _SPLIT_CONFIDENCE >= threshold:
        sig_by_key: dict[str, set[str]] = {}
        split_candidates: list[BankCreditLine] = []
        tied_sids_by_key: dict[str, set[str]] = defaultdict(set)

        for ln in lines:
            if not (ln.is_credit and ln.amount_paise > 0 and not narration_rail_signals(ln)):
                continue
            rzp_signals_list = razorpay_signals(ln, index)
            sigs = {e.signal for e in rzp_signals_list}
            if "utr_exact" in sigs:
                continue

            # Record strong single-credit UTR ties to specific settlements (Finding 4)
            for e in rzp_signals_list:
                if e.signal == "utr_suffix":
                    m = re.search(r"settlement_utr\s+([a-z0-9]+)", e.detail, re.I)
                    if m:
                        sid = index.utr_to_sid.get(m.group(1).lower())
                        if sid:
                            tied_sids_by_key[ln.key].add(sid)

            if _RZP_LEANING_SIGNALS & sigs:
                split_candidates.append(ln)
                sig_by_key[ln.key] = sigs

        for sid in sorted(index.settlement_net):
            net = index.settlement_net[sid]
            sdate = index.settlement_date.get(sid)
            if net <= 0 or sdate is None:
                continue

            # Credits with strong UTR tie to a different settlement are excluded (Finding 4)
            elig = [
                c for c in split_candidates
                if c.amount_paise < net
                and abs((c.value_date - sdate).days) <= _SPLIT_DATE_WINDOW
                and (not tied_sids_by_key.get(c.key) or sid in tied_sids_by_key[c.key])
            ]
            if len(elig) < 2:
                continue

            # Bound actual work: combinations check per SC-005 (Bug 6)
            n_elig = len(elig)
            n_combos = (n_elig * (n_elig - 1)) // 2 + (n_elig * (n_elig - 1) * (n_elig - 2)) // 6
            if n_elig > max_candidates or n_combos > max_combinations:
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
                # Attach split_reconstruction evidence + strong-signal proof (Bug 7)
                split_ev: list[EvidenceItem] = [
                    EvidenceItem(
                        "split_reconstruction",
                        f"1 of {len(sub)} bank legs whose amounts uniquely sum to balance the settlement net for {sid}",
                        _SPLIT_CONFIDENCE,
                    )
                ]
                for c in sub:
                    for sig in _STRONG_RZP_SIGNALS:
                        if sig in sig_by_key.get(c.key, set()):
                            for item in razorpay_signals(c, index):
                                if item.signal == sig and item not in split_ev:
                                    split_ev.append(item)

                candidates.append(
                    CandidateAssignment(
                        assignment_id=f"split:{sid}:{'+'.join(sub_keys)}",
                        credit_keys=sub_keys,
                        target_id=sid,
                        rail=Rail.RAZORPAY_SETTLEMENT.value,
                        tier=Tier.C.value,
                        confidence=_SPLIT_CONFIDENCE,
                        evidence=tuple(split_ev),
                        residual_paise=residual,
                        cost_tuple=cost,
                        is_split=True,
                    )
                )

    # A credit poisoned by ANY oversized/un-enumerable split pool must abstain from ALL split
    # assignments — we could not enumerate its globally-competing splits, so accepting any split for it
    # would be an unverified verdict (Qodo: "stale splits bypass abstention"). This also drops split
    # edges emitted for an EARLIER settlement before the credit was poisoned by a later, larger pool.
    # Its own single-credit edges are untouched (its individual tie is still proof).
    if un_enumerable_credits:
        candidates = [
            c for c in candidates
            if not (c.is_split and any(k in un_enumerable_credits for k in c.credit_keys))
        ]

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


def _add_costs(
    a: tuple[int, int, int, float, float],
    b: tuple[int, int, int, float, float],
) -> tuple[int, int, int, float, float]:
    return (
        a[0] + b[0],
        a[1] + b[1],
        a[2] + b[2],
        round(a[3] + b[3], 4),
        round(a[4] + b[4], 4),
    )


def _solve_component(
    graph: AssignmentGraph,
    comp_set: set[str],
    global_consumed_settlements: set[str],
    excluded_assignment_ids: set[str] | None = None,
    max_steps: int = _MAX_BRANCH_STEPS,
) -> tuple[list[CandidateAssignment], tuple[int, int, int, float, float], bool]:
    """Solve one connected component using branch-and-bound search.

    Optionally excludes specified candidate assignment IDs (to find the best alternative).
    Returns (best_assignment, best_cost, timed_out).
    """
    excluded = excluded_assignment_ids or set()
    best_cost: tuple[int, int, int, float, float] | None = None
    best_assignment: list[CandidateAssignment] = []
    steps = 0
    step_budget_exceeded = False

    # Baseline: default abstain for all credits in component (if available)
    default_chosen = [
        c for k in sorted(comp_set)
        for c in graph.candidates_by_credit.get(k, [])
        if c.target_id == "abstain" and c.assignment_id not in excluded
    ]
    default_cost: tuple[int, int, int, float, float] = (0, 0, 0, 0.0, 0.0)
    if len(default_chosen) == len(comp_set):
        for c in default_chosen:
            default_cost = _add_costs(default_cost, c.cost_tuple)
        best_cost = default_cost
        best_assignment = list(default_chosen)

    def search(
        unassigned: set[str],
        comp_consumed_sids: set[str],
        chosen: list[CandidateAssignment],
        current_cost: tuple[int, int, int, float, float],
    ) -> None:
        nonlocal best_cost, best_assignment, steps, step_budget_exceeded
        steps += 1
        if steps > max_steps:
            step_budget_exceeded = True
            return

        if not unassigned:
            if best_cost is None or current_cost < best_cost:
                best_cost = current_cost
                best_assignment = list(chosen)
            return

        next_credit = min(unassigned)
        avail = graph.candidates_by_credit.get(next_credit, [])

        valid_cands = [
            c for c in avail
            if c.assignment_id not in excluded
            and all(k in unassigned for k in c.credit_keys)
            and (
                c.target_id not in graph.settlements
                or (c.target_id not in global_consumed_settlements and c.target_id not in comp_consumed_sids)
            )
        ]

        valid_cands.sort(key=lambda c: (c.cost_tuple, c.credit_keys, c.target_id, c.assignment_id))

        for c in valid_cands:
            if step_budget_exceeded:
                return
            tentative_cost = _add_costs(current_cost, c.cost_tuple)

            if best_cost is not None and tentative_cost[:2] > best_cost[:2]:
                continue

            new_consumed = set(comp_consumed_sids)
            if c.target_id in graph.settlements:
                new_consumed.add(c.target_id)

            new_unassigned = unassigned - set(c.credit_keys)
            chosen.append(c)
            search(new_unassigned, new_consumed, chosen, tentative_cost)
            chosen.pop()

    search(set(comp_set), set(), [], (0, 0, 0, 0.0, 0.0))
    if step_budget_exceeded:
        return (default_chosen, default_cost, True)
    if best_cost is None:
        return ([], (999, 999999999, 999999999, 0.0, 999.0), False)
    return best_assignment, best_cost, False


def solve_assignment(
    graph: AssignmentGraph,
    *,
    margin_threshold: float = 0.0,
    max_steps: int = _MAX_BRANCH_STEPS,
) -> SolverResult:
    """Solve the constrained assignment problem using deterministic branch-and-bound.

    Pure function:
    - Minimizes the 5-component lexicographic objective tuple:
      (invalid_picks, unexplained_paise, residual_paise, -evidence_weight, ops_cost)
    - Hard constraints:
      1. Each credit assigned exactly once.
      2. Each settlement net consumed at most once.
      3. Splits provable within date window/tolerance.
    - Connected components: solves independent credit/settlement clusters.
    - Oversized/un-enumerable components fail-closed to safe abstention.
    - Emits rejected_matches recording the violated constraints for non-selected options.
    - When margin_threshold > 0.0: computes best alternative globally valid assignments.
      If the objective gap is within margin_threshold, contested credits abstain carrying
      both competing explanations.
    """
    if not graph.credits:
        return SolverResult(
            verdicts={},
            consumed_settlements=set(),
            objective_cost=(0, 0, 0, 0.0, 0.0),
            rejected_matches=[],
            is_optimal=True,
        )

    all_chosen_assignments: list[CandidateAssignment] = []
    consumed_settlements: set[str] = set()
    contested_credits: dict[str, dict[str, Any]] = {}
    is_overall_optimal = True
    overall_notes: list[str] = []
    if graph.un_enumerable_credits:
        is_overall_optimal = False
        overall_notes.append("Oversized candidate pool marked un-enumerable (abstain)")

    for comp in graph.components:
        comp_credits = list(comp)
        comp_set = set(comp_credits)

        # Solve component with branch-and-bound search
        best_assignment, best_cost, timed_out = _solve_component(
            graph, comp_set, consumed_settlements, max_steps=max_steps
        )
        if timed_out:
            is_overall_optimal = False
            overall_notes.append(f"Component branch-and-bound step limit exceeded ({max_steps} steps); failed-closed to abstention")

        # Global competing-explanation margin evaluation (Phase 3)
        if margin_threshold > 0.0 and best_assignment:
            for c_star in best_assignment:
                if c_star.target_id == "abstain" or c_star.rail == Rail.UNKNOWN.value:
                    continue

                # Search for best alternative assignment excluding c_star
                alt_assignment, alt_cost, _ = _solve_component(
                    graph,
                    comp_set,
                    consumed_settlements,
                    excluded_assignment_ids={c_star.assignment_id},
                    max_steps=max_steps,
                )

                # Two worlds are "equally valid" only when they tie on the harder objective tiers —
                # invalid picks, unexplained paise, AND residual paise. Only then is the evidence-weight
                # gap (tier 4) the deciding margin. (Bug: comparing only [:2] let a worse-residual
                # alternative trigger a false abstention.)
                if alt_assignment and alt_cost[:3] == best_cost[:3]:
                    gap = round(alt_cost[3] - best_cost[3], 4)
                    if gap <= margin_threshold:
                        alt_by_credit = {k: c for c in alt_assignment for k in c.credit_keys}
                        for k in c_star.credit_keys:
                            c_alt = alt_by_credit.get(k, c_star)
                            contested_credits[k] = {
                                "chosen": {
                                    "assignment_id": c_star.assignment_id,
                                    "target_id": c_star.target_id,
                                    "rail": c_star.rail,
                                    "confidence": c_star.confidence,
                                },
                                "competing": {
                                    "assignment_id": c_alt.assignment_id,
                                    "target_id": c_alt.target_id,
                                    "rail": c_alt.rail,
                                    "confidence": c_alt.confidence,
                                },
                                "objective_gap": gap,
                                "margin_threshold": margin_threshold,
                                "detail": (
                                    f"Competing global assignment exists with objective gap "
                                    f"{gap:.4f} <= {margin_threshold:.4f}"
                                ),
                            }

        for c in best_assignment:
            all_chosen_assignments.append(c)
            # Only record settlement as consumed if not all of its credits are contested
            if c.target_id in graph.settlements:
                if not all(k in contested_credits for k in c.credit_keys):
                    consumed_settlements.add(c.target_id)

    # Compute overall objective cost
    total_invalid = sum(c.cost_tuple[0] for c in all_chosen_assignments)
    total_unexplained = sum(c.cost_tuple[1] for c in all_chosen_assignments)
    total_residual = sum(c.cost_tuple[2] for c in all_chosen_assignments)
    total_neg_ev = round(sum(c.cost_tuple[3] for c in all_chosen_assignments), 4)
    total_ops_cost = round(sum(c.cost_tuple[4] for c in all_chosen_assignments), 4)
    overall_cost = (total_invalid, total_unexplained, total_residual, total_neg_ev, total_ops_cost)

    # Determine rejected matches and violated constraints
    chosen_assignment_ids = {c.assignment_id for c in all_chosen_assignments}
    chosen_by_target: dict[str, CandidateAssignment] = {
        c.target_id: c for c in all_chosen_assignments if c.target_id in graph.settlements
    }

    rejected_matches: list[dict[str, Any]] = []
    for cand in graph.candidates:
        if cand.assignment_id in chosen_assignment_ids:
            continue
        if cand.target_id == "abstain":
            continue

        if cand.target_id in graph.settlements and cand.target_id in consumed_settlements:
            winner = chosen_by_target.get(cand.target_id)
            winner_keys = winner.credit_keys if winner else ()
            rejected_matches.append({
                "credit_keys": cand.credit_keys,
                "candidate_id": cand.assignment_id,
                "target_id": cand.target_id,
                "rail": cand.rail,
                "violated_constraint": "settlement_already_consumed",
                "detail": f"Settlement {cand.target_id} was consumed by globally consistent assignment for credit(s) {winner_keys}",
            })
        else:
            rejected_matches.append({
                "credit_keys": cand.credit_keys,
                "candidate_id": cand.assignment_id,
                "target_id": cand.target_id,
                "rail": cand.rail,
                "violated_constraint": "suboptimal_objective",
                "detail": f"Candidate {cand.assignment_id} rejected in favor of globally higher-ranked assignment",
            })

    rejected_matches.sort(key=lambda r: (r["candidate_id"], r["credit_keys"]))

    # Build verdicts
    verdicts: dict[str, CreditAssignmentVerdict] = {}
    chosen_by_credit: dict[str, CandidateAssignment] = {}
    for c in all_chosen_assignments:
        for k in c.credit_keys:
            chosen_by_credit[k] = c

    for k in sorted(graph.credits.keys()):
        c = chosen_by_credit.get(k)
        k_rejected = tuple(r for r in rejected_matches if k in r["credit_keys"])
        if k in contested_credits:
            verdicts[k] = CreditAssignmentVerdict(
                line_key=k,
                rail=Rail.UNKNOWN.value,
                target_id="abstain",
                confidence=0.0,
                tier=Tier.B.value,
                evidence=(),
                abstained=True,
                residual_paise=0,
                covered_split_keys=(),
                competing_global_explanation=contested_credits[k],
                rejected_local_matches=k_rejected,
            )
        elif c is None or c.target_id == "abstain" or c.rail == Rail.UNKNOWN.value:
            verdicts[k] = CreditAssignmentVerdict(
                line_key=k,
                rail=Rail.UNKNOWN.value,
                target_id="abstain",
                confidence=0.0,
                tier=Tier.B.value,
                evidence=(),
                abstained=True,
                residual_paise=0,
                covered_split_keys=(),
                competing_global_explanation=None,
                rejected_local_matches=k_rejected,
            )
        elif c.rail == Rail.RAZORPAY_SETTLEMENT.value:
            verdicts[k] = CreditAssignmentVerdict(
                line_key=k,
                rail=Rail.RAZORPAY_SETTLEMENT.value,
                target_id=c.target_id,
                confidence=c.confidence,
                tier=c.tier,
                evidence=c.evidence,
                abstained=False,
                residual_paise=c.residual_paise,
                covered_split_keys=c.credit_keys if c.is_split else (),
                competing_global_explanation=None,
                rejected_local_matches=k_rejected,
            )
        else:
            verdicts[k] = CreditAssignmentVerdict(
                line_key=k,
                rail=c.rail,
                target_id=c.target_id,
                confidence=c.confidence,
                tier=c.tier,
                evidence=c.evidence,
                abstained=False,
                residual_paise=0,
                covered_split_keys=(),
                competing_global_explanation=None,
                rejected_local_matches=k_rejected,
            )

    note = "; ".join(overall_notes) if overall_notes else None

    return SolverResult(
        verdicts=verdicts,
        consumed_settlements=consumed_settlements,
        objective_cost=overall_cost,
        rejected_matches=rejected_matches,
        is_optimal=is_overall_optimal,
        note=note,
    )


def run_global_solver(
    lines: list[BankCreditLine],
    index: ReconIndex,
    base_attributions: list[RailAttribution],
    *,
    threshold: float = 0.55,
    margin_threshold: float = 0.0,
    max_candidates: int = _SPLIT_MAX_CANDIDATES,
    max_combinations: int = _MAX_SPLIT_COMBINATIONS,
) -> tuple[list[RailAttribution], SolverResult]:
    """Run the global evidence-constrained reconciliation solver.

    Takes initial per-line candidate attributions, builds the candidate graph,
    solves the constrained assignment problem, and returns:
    1. Adjusted list[RailAttribution] reflecting globally consistent verdicts.
    2. SolverResult containing verdicts, objective costs, and rejected matches.
    """
    graph = build_candidate_graph(
        lines,
        index,
        base_attributions,
        max_candidates=max_candidates,
        max_combinations=max_combinations,
        threshold=threshold,
    )
    result = solve_assignment(graph, margin_threshold=margin_threshold)

    out: list[RailAttribution] = []
    base_by_key = {a.line_key: a for a in base_attributions}

    for ln in lines:
        if ln.key not in result.verdicts:
            orig = base_by_key.get(ln.key)
            if orig is not None:
                out.append(orig)
            continue

        v = result.verdicts[ln.key]
        orig = base_by_key.get(ln.key)

        if v.abstained:
            if orig is not None and v.competing_global_explanation is not None:
                out.append(
                    RailAttribution(
                        line_key=ln.key,
                        rail=Rail.UNKNOWN.value,
                        confidence=orig.confidence,
                        tier=orig.tier,
                        evidence=orig.evidence,
                        abstained=True,
                        llm_used=orig.llm_used,
                        proof_margin=v.competing_global_explanation.get("objective_gap"),
                        competing_explanation=v.competing_global_explanation,
                    )
                )
            elif orig is not None:
                out.append(
                    RailAttribution(
                        line_key=ln.key,
                        rail=Rail.UNKNOWN.value,
                        confidence=0.0,
                        tier=Tier.B.value,
                        evidence=orig.evidence,
                        abstained=True,
                        llm_used=orig.llm_used,
                    )
                )
            else:
                out.append(
                    RailAttribution(
                        line_key=ln.key,
                        rail=Rail.UNKNOWN.value,
                        confidence=0.0,
                        tier=Tier.B.value,
                        evidence=[],
                        abstained=True,
                    )
                )
        elif v.rail == Rail.RAZORPAY_SETTLEMENT.value:
            if v.covered_split_keys:
                ev = [
                    EvidenceItem(
                        "split_reconstruction",
                        f"1 of {len(v.covered_split_keys)} bank legs whose amounts uniquely sum to balance the settlement net for {v.target_id}",
                        _SPLIT_CONFIDENCE,
                    )
                ]
                out.append(
                    RailAttribution(
                        line_key=ln.key,
                        rail=Rail.RAZORPAY_SETTLEMENT.value,
                        confidence=v.confidence,
                        tier=Tier.C.value,
                        evidence=ev,
                        abstained=False,
                    )
                )
            else:
                ev = list(v.evidence) if v.evidence else (orig.evidence if orig else [])
                tier_val = Tier.A.value if any(e.signal == "utr_exact" for e in ev) else Tier.B.value
                out.append(
                    RailAttribution(
                        line_key=ln.key,
                        rail=Rail.RAZORPAY_SETTLEMENT.value,
                        confidence=v.confidence,
                        tier=tier_val,
                        evidence=ev,
                        abstained=False,
                    )
                )
        else:
            ev = list(v.evidence) if v.evidence else (orig.evidence if orig else [])
            out.append(
                RailAttribution(
                    line_key=ln.key,
                    rail=v.rail,
                    confidence=v.confidence,
                    tier=v.tier,
                    evidence=ev,
                    abstained=False,
                )
            )

    return out, result

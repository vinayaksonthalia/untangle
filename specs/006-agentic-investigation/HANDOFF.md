# Feature 006 — Agentic Exception-Investigation Loop (Antigravity hand-off spec)

> **This is the build spec for Antigravity.** Author: Claude (design + review). Antigravity builds it
> self-contained on a feature branch, opens a PR, Claude runs `/review`, fixes Qodo findings, merges.
> **Do not touch `main` directly. Do not change any existing verdict, metric, or reconciliation number.**
>
> Read [docs/BUILD_PLAN.md](../../docs/BUILD_PLAN.md) and [docs/STRATEGY.md](../../docs/STRATEGY.md) §6c
> first. This feature is the **30% "agentic" rubric pillar** — the single highest-value thing left.

---

## 1. Why this exists (the one-paragraph pitch)

The Active Recovery Controller (`engine/recovery.py`, feature 005) already answers **breadth**: "across
all unresolved credits, which *evidence-acquisition* action resolves the most money per unit cost?"
(export the settlement report, confirm a UTR with the bank). That handles credits blocked by **missing
data**. It does **not** handle the harder, more impressive case: a Razorpay credit that **is** matched
to a settlement but whose **money doesn't tie out** — the recon-failure class (`unbalanced_residual`,
`partial_or_duplicate_settlement`, `reconstructed_split_leg`). There, the data is present; the *work* is
**explaining the delta** and **drafting the corrective book entry**. Feature 006 is the agent that does
exactly that, deterministically, with a visible reasoning trace and an LLM used only to narrate.

This is what the rubric rewards ("an agent that closes one finance-ops loop … handles one failure
gracefully") and what an LLM-chat-wrapper competitor cannot do without hallucinating.

## 2. Hard constraints (non-negotiable — Claude will reject the PR otherwise)

1. **Deterministic core.** Root-cause classification and the corrective journal are computed from the
   data by pure functions. **No LLM in the decision path.** The LLM (via the existing `engine/llm/`
   seam) may only produce the *human narration string* of an already-decided result — and the feature
   must work fully with the LLM disabled (narration falls back to a deterministic template).
2. **Additive & read-only.** Must not change any attribution, reconciliation, fee-GST, headline metric,
   or existing test. No money movement. The drafted corrective journal is a *proposal*, never auto-posted.
3. **Abstain over guess.** If the residual cannot be explained to within a tight tolerance by the known
   root-cause classes, return `root_cause = "unexplained"` with the candidates tried — never force one.
4. **Honest framing.** Amounts are "proposed correction of ₹X", evidence-cited, never "owed".
5. **stdlib-only** in the decision path (matches the repo; LLM narration is already optional).

## 3. What to build

### 3a. `engine/investigate.py` (new module — the deterministic core)

A pure function:

```
investigate(line, attribution, reconciliation, recon_rows, index, exception) -> Investigation
```

where `Investigation` is a frozen dataclass with `.to_dict()`:
- `line_key: str`
- `variance_paise: int` — the signed delta between the bank credit and the reconciled/expected net.
- `root_cause: str` — one of the taxonomy in §3b (or `"unexplained"`).
- `confidence: float` — deterministic score of how cleanly the delta is explained (0..1).
- `reasoning_trace: list[str]` — the ordered, human-readable steps the agent took to reach the verdict
  (e.g. "expected net from settlement = ₹9,000", "bank credit = ₹8,982", "delta = −₹18",
  "candidate: MDR/fee drift → fee-slab recompute yields −₹18 → MATCH"). This is the audit trail; it must
  be reproducible and contain no LLM output.
- `corrective_entry: dict | None` — a **balanced** double-entry draft (reuse `engine/journal.py`
  builders and their exact sign convention) that would post the explained delta; `None` when unexplained.
- `candidates_tried: list[dict]` — every root-cause class evaluated, with pass/fail + computed delta, so
  a reviewer sees the negative space (why the others were rejected).

### 3b. Root-cause taxonomy (deterministic classifiers, tried in this order)

Each classifier takes the variance + the settlement/recon data and returns (matches: bool, explained_paise,
evidence). **Do NOT invent categories** beyond this list without a research citation in STRATEGY §6b.
Ground each in the real settlement schema (STRATEGY §6b confirmed columns: `fee, tax, on_hold, debit,
credit, amount, dispute_id, settled_at, created_at, …`).

| Root cause | Deterministic test |
|-----------|--------------------|
| `mdr_fee_drift` | Recompute expected net with fee (± the tax-inside/outside convention already detected by `journal._tax_inside_fee`); delta closes to ~0. |
| `cross_cycle_refund_lag` | A refund/debit row whose `created_at` is in-cycle but `settled_at` lands in a later cycle exactly accounts for the delta. |
| `on_hold_release` | `on_hold` amount held from this cycle (or released into it) equals the delta. |
| `dispute_deduction` | A row carrying `dispute_id` with a deduction equal to the delta. |
| `partial_capture` | Captured amount < authorized for a payment in the settlement, delta matches. |
| `bank_charge_or_rounding` | Residual ≤ a tight ₹ threshold (reuse the existing accepted-residual tolerance) → rounding line. |
| `rolling_reserve` | A reserve withheld/released component equals the delta (only if the schema carries it; else skip). |
| `unexplained` | None of the above closes the delta within tolerance → abstain, list candidates_tried. |

Reuse, don't reinvent: `engine/recovery.py::resolve_delta` (line ~522) and `_derive_blocking_reason`
already touch delta reasoning — extend/compose them, keep them green.

### 3c. Wiring (thin, additive)

- `engine/cli.py::build_report` — attach `investigations` (list) for the recon-failure exceptions only,
  alongside the existing recovery plan. Guard so headline metrics are byte-identical to today.
- `engine/models.py` — add an optional `investigations: list[dict] | None = None` field on the report,
  serialized in `to_dict` (mirror how `journal` / recovery plan were added).
- `mcp_server.py` — add one read-only tool `investigate_variance(bank, recon, ledger, line_key)` that
  returns the `Investigation.to_dict()`. Fail-safe `{ok: false, error, error_type}` like the others.

### 3d. UI (`ui/dashboard.py`, additive)

- In the exception queue, add an **"Investigate"** control on each recon-failure row that reveals the
  `reasoning_trace` (as an ordered list), the `root_cause` badge, `candidates_tried` (with the rejected
  ones visibly struck), and the drafted `corrective_entry` with a "this is a proposal, not posted" note.
- This is the demo's show-stopper moment — make the reasoning trace legible, not a JSON dump.

## 4. Tests (required, test-first where sensible)

- `tests/unit/test_investigate.py` — **one test per root-cause class**: construct a settlement + bank
  credit that exhibits exactly that variance, assert the classifier picks it, the `corrective_entry`
  balances, and the `reasoning_trace` names the right numbers. Plus: an `unexplained` case (delta that no
  class closes → abstains, lists candidates_tried).
- `tests/property/test_investigate_additive.py` — property tests: (a) running investigation does not
  change any headline metric vs a report built without it (additivity); (b) determinism (same input →
  identical `to_dict()`); (c) every non-`None` `corrective_entry` is balanced (debits == credits).
- Extend `tests/unit/test_mcp_server.py` with the new tool.

## 5. Docs (part of the same PR — not optional; see BUILD_PLAN §5)

- New `docs/AGENTIC_INVESTIGATION.md` (mirror `docs/ACTIVE_RECOVERY.md`): what it is, the taxonomy, the
  deterministic-core/LLM-narration boundary, a worked example with a real reasoning trace.
- `docs/EXCEPTION_TAXONOMY.md` — cross-reference the root-cause classes.
- `README.md` — one line under features + the agentic pillar in the pitch.
- `docs/BUILD_PLAN.md` §2/§3 — flip feature 006 to DONE on merge (Claude does this at merge).

## 6. Definition of done

Deterministic root-cause classification + balanced corrective-journal draft + reproducible reasoning
trace + "Investigate" UI + MCP tool, **all additive**, tests per root-cause class green, docs shipped in
the same PR, headline metrics byte-identical. LLM disabled → still fully works (template narration).

## 7. Open research feeding this (Claude writes prompts, U runs, before/while building)

The §3b taxonomy is grounded but should be validated against reality — see
[docs/RESEARCH_QUEUE.md](../../docs/RESEARCH_QUEUE.md) Q1 (exhaustive real list of *why* a Razorpay
settlement credit fails to tie out). If research surfaces a class we're missing, add it with a citation.

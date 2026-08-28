# untangle — Living Build Plan

> **The master execution plan.** Who does what, in what order, and how we keep the product (and its
> docs) honest as it grows. This is a *living* document — every merged feature updates the status here
> AND the relevant docs (README, taxonomy, ACTIVE_RECOVERY, this file). See §5 "Doc discipline".
>
> **Why we're building this way:** this is not a demo. It's a product meant to *beat* Razorpay's own
> Agentic Reconciliation on the merchant side, judged for an internship. That means: real accounting
> output, deterministic correctness, an audit trail a payments engineer will believe, and usability a
> judge can grasp in 60 seconds. Strategy rationale lives in [STRATEGY.md](STRATEGY.md); this file is
> the *execution* layer on top of it.

Deadline: **5 Sep 2026**. Track 4 — AI Finance Controller.

---

## 1. Roles (who owns what)

- **C (Claude)** — design, specs, correctness review, security review, the courtroom/verifier/journal/
  UI surfaces, docs, all merges. Writes the spec Antigravity builds against; reviews every Antigravity
  PR adversarially (never rubber-stamps green tests).
- **A (Antigravity)** — self-contained feature builds *behind a Claude-written spec*. Output always goes:
  feature branch → PR → standalone `/review` → C fixes Qodo findings → merge. Never direct-to-main.
- **U (Vinayak)** — runs the research prompts (GPT + Gemini), deploys (Render), records the demo video,
  provides/sources one real statement, final product judgment.

## 2. Current state (as of last update)

Everything below is **merged to main, reviewed, zero known bugs**:
Evidence Courtroom · honest 4-label taxonomy · journal export (Tally XML + JSON, convention-agnostic) ·
independent verifier + signed close certificate + /verify · MCP server (9 read-only tools) ·
**Active Recovery Controller** (ranked next-best actions, info-gain, recovery trail) · BYOD upload polish.

We estimate ~80% of the Track-4 rubric is already covered. **The gap is the 30% "agentic" pillar** —
that is the top of the queue below.

## 3. The plan — sequenced by (impact on winning ÷ effort)

### NOW (in flight / next up)

| Seq | Item | Owner | Definition of done |
|-----|------|-------|--------------------|
| 1 | **Agentic exception-investigation loop** (feature 006) — the 30% pillar. Spec: [specs/006-agentic-investigation/HANDOFF.md](../specs/006-agentic-investigation/HANDOFF.md) | **A** builds, **C** specs+reviews | For an unresolved variance: deterministic root-cause classification + drafted corrective journal + visible reasoning trace + "Investigate" UI. LLM narrates only. Tests per root-cause class. |
| 2 | **README + pitch reframe** to §1 + official Track-4 language | **C** | Headline leads with validated pain (5%-eats-80%, 78%-tax abstention, "closes one finance-ops loop over 50+ records"), not "which credit is Razorpay's". |
| 3 | **Deploy public URL** (Render) | **U** | Judge can click a live URL; sample data loads; BYOD works. |

### SOON

| Seq | Item | Owner | Definition of done |
|-----|------|-------|--------------------|
| 4 | **Docs pass** — web/CLI/MCP/API usage, 60-sec quickstart | **C** | A judge can run every surface from the docs alone (the Lethe lesson). |
| 5 | **Real bank-statement / Razorpay-export ingestion** — HDFC/ICICI/SBI/Axis/Kotak/RBL adapters (headers+UTR regex already in STRATEGY §6b) | **A** (spec by C) | A real bank CSV + a real Razorpay settlement export ingest and reconcile. |
| 6 | **One real statement in the demo** | **U/C** | Razorpay's published sample (or a real merchant export) runs end-to-end. |

### LATER (only if time; do not chase)

| Seq | Item | Owner | Note |
|-----|------|-------|------|
| 7 | TDS / statutory-correctness layer (194-O, ITC-vs-GSTR-2B) | A/C | Neutralizes a peer's only edge (STRATEGY §6d). Not P0. |
| 8 | Demo video (5-min: fake-UTR refusal + forge-cert-live + the "2 AM bug") | U | Submission requirement — record once features freeze. |

**Explicitly NOT now** (STRATEGY §5): COD/3PL recon, fraud, chargebacks, forecasting, generic CFO chat,
multi-agent framework. These dilute the identity. Post-buildathon roadmap only.

## 4. Research we still owe ourselves (U runs, C writes prompts + verifies)

Research is not done — it feeds the build. Open questions to send to GPT + Gemini (prompts in
[docs/RESEARCH_QUEUE.md](RESEARCH_QUEUE.md)):
1. **Root-cause taxonomy for settlement variances** — the exhaustive, real list of *why* a Razorpay
   credit fails to reconcile (cross-cycle refund lag, MDR/fee-slab drift, partial capture, on-hold
   release, dispute deduction, bank charge, rolling-reserve). This directly shapes feature 006's
   deterministic classifier — we must not invent categories.
2. **Razorpay Agentic Reconciliation** — exactly what the incumbent does and where the merchant-side
   boundary (bank statement, on-prem Tally) leaves it blind. Sharpens the "why not Razorpay?" defense.
3. **What a real CA/finance-ops lead needs to trust automated books** — the acceptance bar for the
   journal output and the audit trail.

Every research finding lands in STRATEGY.md §6b/§6c with a source, verified against code before we act.

## 5. Doc discipline (the rule we keep breaking — enforce it)

**Every merged feature updates its docs in the same PR.** No "docs later". Specifically:
- New reason code / exception class → `docs/EXCEPTION_TAXONOMY.md` + dashboard label.
- New surface or capability → `README.md` (features + quickstart) + this file's §2/§3 status.
- New research finding → `STRATEGY.md` §6b (verified, sourced, newest-first).
- New feature → its own `docs/<FEATURE>.md` (like `docs/ACTIVE_RECOVERY.md`).
- Status changes here in `BUILD_PLAN.md` §2/§3 whenever something merges.

If a PR adds capability but not docs, it is **not done**. C enforces this at review.

## 6. The bar (what "winning" means, so we don't drift)

- **Deterministic core, LLM only for narration.** An LLM guessing a debit or a root cause is the
  rubric's disqualifier. Every number and every verdict is provable without the LLM.
- **Abstain over guess.** A wrong match in India can attract ~78% tax (§115BBE) — precision is a
  financial safeguard, not a nicety.
- **Usable on every surface** (web + CLI + MCP + API) with docs — the Lethe factor that wins.
- **Real accounting output** (postable Tally/Zoho entry) — what makes merchants/CAs actually pay.

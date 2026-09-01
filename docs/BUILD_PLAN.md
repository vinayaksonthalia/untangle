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

## 2. Current state (updated 1 Sep 2026 UTC)

**Merged to main, reviewed** — Evidence Courtroom · honest 4-label taxonomy · journal
export (Tally XML + JSON, convention-agnostic) · independent verifier + close certificate + /verify ·
**MCP server (stdio + streamable HTTP, read-only)** · **Active Recovery Controller** · **Agentic
Exception-Investigation Loop (feature 006, PR #26, 14 correctness bugs caught+fixed in review)** · README
overclaim fixes (#25) · UTC-determinism fix (#27) · BYOD polish.

**UI (in Stitch, not yet in the app):** all 5 screens designed + premium-polished (motion, count-ups,
copy-to-clipboard, tooltips, FAQ, framed hero preview). Stitch MCP connected. **Not yet wired into the
FastAPI app** — that's the next big C task.

Our interpretation of the Track-4 requirements is now well covered. The remaining work is about **competitive differentiation,
polish, shipping (deploy), and the demo** — informed by a competitor review (Agent-Audit, Track 01) and
our own research (see §4a competitive learnings).

**Phase 1 exit review: CONDITIONAL PASS.** Tasks 4–6 are merged and the executable exit gates pass;
see [PHASE1_EXIT_REVIEW.md](PHASE1_EXIT_REVIEW.md). The dedicated SBI adapter remains blocked on a
sanitized authentic SBI export fixture. Synthetic narration coverage must not be presented as native
SBI-format validation.

## 3. The master backlog — sequenced by (impact on winning ÷ effort)

Owner: **C**=Claude · **A**=Antigravity (behind a C spec, C reviews) · **U**=Vinayak. Everything ships via
branch → PR → `/review` → fix all bot findings → **manual** merge (never auto-merge, never direct-to-main).

### NOW — highest leverage

| # | Item | Owner | Risk | Definition of done |
|---|------|-------|------|--------------------|
| 1 | **Wire the polished Stitch UI into the real FastAPI app** — export the 5 screens' HTML, integrate with real data/routes, then click-through-and-break it live | **C** | **HIGH** (integration; C does it) | Every screen renders from real engine output; motion/copy/tooltips/FAQ work; no interaction bugs; responsive. |
| 2 | **Remote (streamable-HTTP) MCP** — a public endpoint a judge can call from ChatGPT / Claude.ai with no local install | **A** (spec by C), C reviews | MED | **DONE (merged in PR #29/#30)** — `/mcp` streamable-HTTP transport exposes the read-only tools; public-host verification remains deployment work. |
| 3 | **Confidence intervals on headline metrics** — wrap precision/recall (and the coverage curve) in bootstrap CIs; label any partial/degraded run (rigor, like Agent-Audit) | **C** | LOW | Eval reports each headline number with a 95% CI; README/dashboard show "± CI"; no bare point claims. |
| 4 | **Deploy public URL** (Render) | **U** | — | Judge clicks a live URL; sample loads; BYOD works. |
| 5 | **Duplicate-key covered-row identity fix** — reconcile must preserve WHICH covered row (feegst/proof/journal/investigate pick by lossy key today). Deferred from #27; task chip spawned. | **C leads** (spec + build; correctness-sensitive, touches core) | **HIGH** | covered rows carry unambiguous identity; feegst/proof/journal/investigate sum from exact rows; regression test with a non-first duplicate; metrics byte-identical for the common case. |

### SOON — credibility + polish

| # | Item | Owner | Risk | Definition of done |
|---|------|-------|------|--------------------|
| 6 | **`SAFETY.md` + public checkbox roadmap in README** — articulate our guarantees (read-only, no money movement, abstain-not-guess, every verdict proof-backed, independently verifiable) and a ✅/☐ roadmap (Agent-Audit honesty pattern) | **C** | LOW | SAFETY.md exists; README has a done/pending checklist; "safer by design (read-only)" stated. |
| 7 | **₹-at-risk / ₹-recoverable headline model** — one clear business-value number up front (Agent-Audit's Revenue-at-Risk pattern), from unresolved cash + recoverable GST-ITC we already compute | **C** | LOW | Landing + dashboard surface a single ₹ headline with honest "up to / if confirmed" framing. |
| 8 | **Docs pass** — web/CLI/MCP/API usage, 60-sec quickstart | **C** | LOW | A judge can run every surface from the docs alone (Lethe lesson). |
| 9 | **Real bank-statement / Razorpay-export ingestion** — planned HDFC/ICICI/SBI/Axis/Kotak/RBL dedicated adapters against authentic fixtures (see [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md)) | **A** (spec by C) | MED | Authentic bank export fixtures + dedicated adapters ingest and reconcile. |
| 10 | **One real statement in the demo** (Razorpay's published sample) | **U/C** | — | Runs end-to-end; closes the "toy?" question. |

### LATER — only if time

| # | Item | Owner | Note |
|---|------|-------|------|
| 11 | **Demo video** (5-min: fake-UTR refusal + forge-cert-live + the "2 AM bug" = the 14-bug review saga) | U | Record once features freeze. |
| 12 | TDS / statutory-correctness layer (194-O, ITC-vs-GSTR-2B) | A/C | Neutralizes a peer's only edge (STRATEGY §6d). Not P0. |

### What Antigravity builds next (C writes the spec, C reviews adversarially)
- **#2 Remote streamable-HTTP MCP** (well-bounded; untangle is read-only so low blast radius).
- **#9 Real bank/Razorpay-export ingestion adapters** (well-bounded; planned per-provider dedicated adapters against authentic fixtures).
- NOT #1 (UI wiring), #3 (CIs), or #5 (duplicate-key fix) — those are correctness/integration-sensitive
  and **C keeps** them (higher risk; do not delegate).

## 4a. Competitive learnings — from Agent-Audit (Track 01, rated "best overall" by another agent)
Blunt read: genuinely excellent — novel problem + research rigor + **remote MCP implementation**
+ safety-by-design. Deployment and public-host verification remain open. What we steal: **remote MCP (#2)**,
**CIs on metrics (#3)**, **SAFETY.md + checkbox roadmap (#6)**, **₹-at-risk headline (#7)**. Where we win by
design: we're **read-only** (their MCP payment tool is unauthenticated + on their pending list), and we have
no multi-model dependency to stabilize. Their one crack: a "640-trial" headline that's actually 220 in the
live build (multi-model is ☐ pending) — a reminder to keep untangle's **zero-overclaim** discipline.

## 4b. Research status (U runs prompts, C verifies + lands in STRATEGY §6b)
The major research (2 GPT reviews + 4 Gemini rounds) is synthesized in STRATEGY and already built against.
Three open prompts remain in [RESEARCH_QUEUE.md](RESEARCH_QUEUE.md): **Q1** variance root-cause taxonomy
(now validates the shipped 006 — optional), **Q2** Razorpay Agentic Recon (sharpens the defense), **Q3** CA
trust bar. **We are research-sufficient to win** — run Q1 to double-check 006 if desired; otherwise pour
energy into build + deploy + demo. Do NOT over-research.

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
  strategy's safety bar. Every number and every verdict is provable without the LLM.
- **Abstain over guess.** A wrong match in India can attract ~78% tax (§115BBE) — precision is a
  financial safeguard, not a nicety.
- **Usable on every surface** (web + CLI + MCP + API) with docs — the Lethe factor that wins.
- **Real accounting output** (postable Tally/Zoho entry) — what makes merchants/CAs actually pay.

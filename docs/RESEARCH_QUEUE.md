# Research Queue

> Open research questions that feed the build. **U** runs these with GPT + Gemini; **C** wrote the
> prompts and verifies every answer against code/sources before it changes anything. Verified findings
> land in [STRATEGY.md](STRATEGY.md) §6b (sourced, newest-first). An answer is not "true" until C has
> checked it against a real source or the codebase — no unsourced claim drives a build decision.

Status: `OPEN` = not yet run · `IN REVIEW` = answered, C verifying · `LANDED` = in STRATEGY §6b.

---

## Q1 — Root-cause taxonomy for Razorpay settlement variances `[OPEN]` (feeds feature 006)

**Why:** feature 006's deterministic classifier must match reality — we must not invent variance
categories. This is the highest-priority research item.

**Prompt to run (GPT + Gemini, ask for sources):**
> For a merchant in India using Razorpay, a single bank credit is a bulk settlement of many payments. In
> reconciliation, the bank credit amount sometimes does **not** tie out to the expected net from the
> Razorpay settlement report. Give me the **exhaustive, real-world list of root causes** for why a
> Razorpay settlement credit fails to reconcile to the paise — with, for each: (a) how it shows up in the
> settlement report columns (fee, tax, on_hold, amount, debit, credit, dispute_id, settled_at,
> created_at), (b) the sign of the delta it creates, (c) how common it is. Include at least: MDR/fee-slab
> drift, GST-on-fee convention, cross-cycle refund lag, on-hold/rolling-reserve holds and releases,
> dispute/chargeback deductions, partial capture, instant-settlement fees, TDS under 194-O. Cite Razorpay
> docs or merchant/CA sources. Flag anything I'm missing.

**What we do with it:** each confirmed cause becomes (or validates) a classifier in HANDOFF §3b; each
gets a unit test. Unsourced causes are not built.

## Q2 — Razorpay's own Agentic Reconciliation: exact scope + merchant-side blind spots `[OPEN]`

**Why:** sharpens the "why wouldn't Razorpay just build this?" defense (STRATEGY §6c). We win on the
merchant boundary they can't cross (the bank statement, on-prem Tally, 3PL COD).

**Prompt:**
> What exactly does Razorpay's "Agentic Reconciliation" / RazorpayX recon product do today, feature by
> feature? What data does it operate on, and — critically — what is it structurally unable to see because
> it sits inside Razorpay rather than on the merchant's side (their full bank statement across all rails,
> their on-prem Tally, their order ledger, COD/3PL remittances)? Cite Razorpay's own pages and any
> independent write-ups.

## Q3 — The trust bar for automated books (CA / finance-ops lead) `[OPEN]`

**Why:** shapes the audit-trail + journal-output acceptance bar; feeds the "will a CA trust this?"
defense and the docs.

**Prompt:**
> You are a chartered accountant / finance-ops lead at an Indian D2C brand. An automated tool proposes
> journal entries reconciling your Razorpay settlements and drafts corrective entries for variances. What
> would you need to see — evidence, audit trail, controls, export format — before you'd trust and post
> those entries? What would make you immediately distrust it? Be specific about Tally/Zoho import
> expectations and statutory (GST ITC, TDS) correctness.

---

## How to add a new question

Append with an `[OPEN]` status, a "why / feeds which feature" line, and a ready-to-paste prompt that asks
for sources. When answered, move the verified, sourced conclusion to STRATEGY.md §6b and mark it `LANDED`
here with a one-line pointer.

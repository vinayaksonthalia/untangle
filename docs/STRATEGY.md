# untangle — Strategy, Research & Build Plan

Single source of truth for **why** we build what we build. Distilled from two GPT competitive
reviews (569 public buildathon repos) + two Gemini deep market-research rounds (sourced, Aug 2026).
Buildathon: Razorpay AI Buildathon, **Track 4 — AI Finance Controller**, deadline **5 Sep 2026**.

---

## 1. The winning thesis (repositioning)

**untangle is an evidence-grade cash-provenance & settlement controller.** It ingests a merchant's
bank statement + Razorpay settlement report + order ledger, proves which credits are Razorpay's,
decomposes each bulk settlement to the paise (gross → MDR fee → 18% GST ITC → refunds), refuses to
guess when evidence is insufficient (routing to an exception queue), and **hands back a balanced
journal entry ready to post to Tally/Zoho** — with an independently-verifiable audit trail.

**Lead with the validated pain, not the abstraction.** Do NOT headline "which credit is Razorpay's"
(bank narrations already identify the rail — a judge knows this). Headline:
1. **"We solve the 5% edge-case slice that eats 80% of your reconciliation time"** (mangled UTRs,
   split settlements, cross-cycle refunds). Verified: 60–75% of lines match Day-1 on exact UTR;
   only ~1–4% ("Bucket C") is truly un-matchable, yet it consumes 70–80% of manual recon time.
2. **"We refuse to guess — because in India a wrong match can cost 78% in tax."** Section 115BBE:
   an unexplained/mis-matched credit attracts ~78% tax + up to 84% penalty. This makes precision-
   first / abstention a *financial safeguard*, not a nicety. Strongest single validation we have.
3. **GST ITC recovery as the self-funding ROI hook**: "costs ₹X/mo, recovers ~₹15k/mo in unclaimed
   input-tax-credit on gateway fees your accountant is missing." (₹2.16L/yr on ₹50L/mo GMV @ 18%.)

## 2. The Lethe lesson — usability wins (highest-order principle)

Vinayak's Lethe won its hackathon **despite not being top-10 on idea** — because it was the most
**usable and accessible**: fully working on **web + CLI + MCP**, dedicated docs for everything,
**demo data + bring-your-own-data**, and settings for the user's own API key. Judges reward
"I can actually use and understand this in 60 seconds" over idea cleverness. Therefore multi-surface
accessibility + frictionless judge onboarding + excellent docs are **must-haves**, not polish.

## 3. Is the problem real? (Yes — 9/10, sourced)

Real, recurring, painful at scale (>~1,000 orders/mo). Evidence: r/indianstartups & r/Razorpay
merchants on settlement-shortfall mystery and Tally bulk-settlement knock-off pain; finance teams
spend 20–40 hrs/mo (gateway) and 50–60 hrs/mo (COD) reconciling. Razorpay itself sells recon +
"Agentic Reconciliation" — incumbents take it seriously. Honest caveat: our benchmark is synthetic;
one real (even Razorpay's own published sample) statement in the demo would close the "toy?" question.

## 4. What to BUILD — task-phased, with owners

Priority = (impact on winning ÷ effort). Owner: **C**=Claude (design/correctness/review/commit/merge),
**A**=Antigravity (self-contained build behind a Claude spec, Claude reviews), **U**=user.

| # | Feature | Why (evidence) | Owner | Status |
|---|---|---|---|---|
| P0 | **Deploy public URL** (Render; established, not antideploy) | No demo URL = capped score. Judges must click it. | U | pending |
| P0 | **Journal-entry export** (Tally XML `<ENVELOPE>` + clean double-entry JSON) | The #1 "makes them pay" feature AND completes the Track-4 finance loop. Every number already computed (recon slice, MDR, 18% GST ITC, refunds). | C leads, A assists on XML | todo |
| P0 | **Reframe pitch/README** around §1 (5%-eats-80%, 78%-tax abstention, GST ROI, journal deliverable) | Two research rounds; kills the overclaim a judge would attack. | C | todo |
| P1 | **Evidence Courtroom** (one verdict, cross-examined) | The unforgettable demo moment; MILAAN/Kosh can't show it. | C | DONE (data+UI) |
| P1 | **Honest 4-label taxonomy** (proven/non-Razorpay/ambiguous/unattributed) | Kills the alternate-rail overclaim. | C | DONE |
| P1 | **Independent verifier + close certificate** (+ /verify page, download) | "Re-check our claims without trusting us." Trust layer. | A built+C fixed; /verify by C | in progress |
| P1 | **MCP server** (untangle-specific, read-only) | Multi-surface accessibility = the Lethe winning factor; on-theme for an AI-agent buildathon. Wraps existing fns. | A (spec by C) | todo |
| P1 | **Docs pass** (usage for web/CLI/MCP/API, one-glance quickstart) | The Lethe lesson: dedicated docs won it. | C | todo |
| P2 | **Frictionless demo + BYOD polish** (60-sec judge onboarding, sample↔own-data toggle) | Ease-of-use is a decisive judge factor. | C | mostly done (upload page redesigned, month filter) |
| P2 | **Exception queue: pre-computed variance categories** (T+5 refund lag, split leg, etc.) | Research: abstention is valued ONLY with a structured, suggestive queue. | C | partial (recovery controller exists) |
| P2 | **One real statement in the demo** (e.g. Razorpay's published sample) | Closes the "synthetic/toy?" gap. | U/C | todo |
| P3 | 5-min demo video (fake-UTR refusal + forge-cert-live) | Submission requirement. | U | todo |

## 5. What NOT to build (scope discipline — dilutes identity)

Fraud, chargebacks, loans, agentic checkout, cart recovery, generic CFO chatbot, forecasting, a large
multi-agent framework, S3 WORM storage. **COD/3PL remittance recon (Shiprocket/Delhivery)** is a
genuinely sharper *commercial* wedge (5–15% leakage vs 1–2%; $2.2–2.7k/cycle loss) and belongs on the
**post-buildathon roadmap**, but NOT now — the Razorpay track is gateway-focused and it would split
the demo. **CA-firm multi-client distribution** = go-to-market, post-buildathon.

## 6. Market facts worth citing in the pitch (sourced)

- Section 115BBE: ~78% tax + up to 84% penalty on unexplained/mis-matched credits → abstention = safeguard.
- GST ITC on gateway MDR: 18% on ~2% fee = ₹18k/mo (₹2.16L/yr) recoverable on ₹50L/mo GMV.
- 60–75% of bank lines auto-match Day-1; ~1–4% is the hard slice but eats 70–80% of recon time.
- Recon report alone ≈ 30% of the value; the balanced journal entry is what merchants/CAs pay for.
- Willingness to pay: D2C ₹2k–15k/mo; CA firm ₹500–1.2k/client or ₹10k–25k firm license.
- Competitors: Cointab ($149–499/mo, 1–3wk onboarding), ReconPe (marketplace-tilted), Terra Insight
  (enterprise $1–3k/mo). Mid-market "valley of death" between Excel and enterprise = our opening.
- Tally XML voucher import (`Gateway of Tally > Import Data > Vouchers`) + Tally HTTP port 9000;
  Zoho Books REST (`/journalentries`, `/bills`, `/creditnotes`).

## 6b. Update log (findings verified against code, newest first)

- **Real Razorpay settlement-report schema confirmed** (round-3 research, verified): columns
  `entity_id, type, debit, credit, amount, currency, fee, tax, on_hold, settled, created_at,
  settled_at, settlement_id, description, notes, payment_id, settlement_utr, order_id, order_receipt,
  method, card_network, card_issuer, card_type, dispute_id`. **untangle's recon schema already mirrors
  this** → a real Razorpay export is largely already ingestible (the credibility anchor, near-free).
- **Fee/tax convention divergence found & fixed.** Real Razorpay: `credit = amount − fee − tax` (fee is
  ex-GST, tax separate). untangle synthetic: `credit = amount − fee` (GST folded into fee). Verified on
  data/. The journal export now DETECTS the convention per settlement (`_tax_inside_fee`) so MDR-ex-GST
  is correct for BOTH — real uploads reconcile correctly. (Open question for later: align the generator
  to the real tax-separate convention for max fidelity — bigger change, touches pinned tests.)
- **Real bank-statement CSV headers captured** for HDFC/ICICI/SBI/Axis/Kotak/RBL (value date, narration,
  ref, debit, credit, balance) + UTR-in-narration regex patterns per bank + metadata-row quirks (HDFC
  ~5 header rows; RBL/Kotak truncation 50–100 chars). Use to make BYOD accept real bank exports.
- **Razorpay GST invoice**: SAC `997159`, monthly e-invoice with IRN/QR, flows to GSTR-2B Table 4 (ITC).
- **Journal-entry export shipped** (Tally XML + JSON, balanced, convention-agnostic). **MCP server** in
  build (Antigravity) — under review before commit.

## 6c. OFFICIAL Track 4 rubric & winning plan (round-4 research — the north star)

**Official Track 4 prompt (grade against THIS):** "Run the books and the cash position: build an agent
that closes one finance-ops loop across a 50+ record batch, reporting its match rate and the exceptions
it could not resolve. Show the audit trail and one failure handled gracefully."

**Rubric weights (research):** Autonomous ops + agentic architecture + match-rate accuracy, zero
hallucinated debits **30%** · Audit trail + explainable reasoning **25%** · Graceful failure + exception
recovery **20%** · Production eng (MCP/APIs, Docker, real Tally/Zoho import) **15%** · Pitch/video incl.
the "2 AM bug" **10%**. Judges = Razorpay settlement/payments eng + product leaders (built Razorpay Recon)
+ fintech VCs. Winner = deterministic pipeline + agentic exception investigator + real accounting output;
runner-up = an "ask your data" LLM chat wrapper that breaks on messy edge cases.

**untangle already hits ~80%** (audit trail, abstention/exceptions, journal export). **The gap is the 30%
agentic pillar.** Top remaining builds, ranked:
1. **Agentic exception-investigation loop** (the show-stopper): for an unresolved variance, autonomously
   detect → classify ROOT CAUSE from the data (cross-cycle refund, MDR/fee drift, missing UTR, bank
   charge) → draft the corrective balanced journal + next action, with a visible reasoning trace and an
   "Investigate" button. MUST be deterministic-core (root-cause from data) + LLM only for narration —
   NOT an LLM guessing (that's the disqualifier the rubric warns about). Extends the recovery controller.
2. **Our MCP server** (Antigravity, in progress) — the multi-surface + agent checkbox. Optionally CONSUME
   Razorpay's official MCP (github.com/razorpay/razorpay-mcp-server) if deployed against a real test acct
   (won't work on synthetic data — don't fake it).
3. **Journal export UI** (download Tally XML/JSON + "Post to your books" section) — surfacing, mine.
4. **Demo to the official prompt** + one graceful-failure story + the "2 AM bug" (the real fee-inside-fee
   / Tally sign-convention bug we hit are honest candidates).

**Judge attacks + defenses (rehearse):**
- "Why wouldn't Razorpay build this?" → Razorpay can't cross the merchant boundary into their *bank
  statement*, 3PL COD, or on-prem Tally; untangle is the merchant-side external verification controller.
- "Why not a 200-line Python script?" → scripts break on truncated narrations / split settlements; we add
  abstention + agentic root-cause investigation + audit-grade proof.
- "Will a CA trust automated books?" → every match carries a verifiable proof + we ABSTAIN below proof,
  never guess (and a wrong match in India risks a 78%-tax-class unexplained credit).

**Reframe the pitch to the official language:** "an agent that closes the settlement finance-ops loop
over 50+ records, reports match rate + the exceptions it refuses to guess, proves every verdict, hands
you the postable Tally entry, and handles failure gracefully."

## 7. Roadmap (post-buildathon, do NOT chase now)

COD/3PL remittance recon (weight-dispute auditing), CA-firm multi-client workspaces, live Razorpay/
bank-feed connectors (Account Aggregator), direct Tally HTTP push. Record here; build later.

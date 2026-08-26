# Feature Specification: Attribution-First Finance Controller

**Feature Branch**: `002-autonomous-finance-controller`

**Created**: 2026-08-26 (rewritten to narrowed scope 2026-08-26)

**Status**: Draft

**Input**: Narrowed after competitive research: 261 public Track-4 repos, 8 with code, **0 doing
source attribution** — all do matching. The wedge is attribution of commingled credits. Rigor
(failure logs, adversarial synthetic data, bounded AI) is now table-stakes, not an edge. The
edge is one module wide (attribution) and must be built deepest and evaluated so it cannot be
dismissed. Scope is deliberately cut to protect that edge.

## Positioning (the one sentence)

> "An attribution-first finance controller that **refuses to reconcile money it cannot prove
> belongs to Razorpay**. A false match is worse than no match — it optimizes for provable
> attribution, not vanity recall."

## Context & the wedge

A merchant's business bank account is a pile of **commingled** credits — Razorpay settlements
mixed with a second gateway, direct UPI, COD remittances, and personal transfers. Every existing
tool (including Razorpay's own shipped "Intelligent Reconciliation") **assumes the credit is
already known to be Razorpay's and just matches UTRs**. This product solves the upstream step
nobody else does: it **attributes each bank credit to its true source rail** with calibrated
confidence and **abstains** when it cannot prove attribution, because a wrong "this is Razorpay's"
corrupts the books. Only after a credit is proven Razorpay's is it reconciled to the paise and its
recoverable fee-GST (input tax credit) surfaced. Everything in this spec exists to make that
attribution edge real and un-dismissable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Attribute commingled credits, abstaining when unproven (Priority: P1) — THE EDGE

Given a merchant's raw bank statement with commingled credits plus the available source files
(Razorpay settlement report, order ledger, and other-gateway/UPI/COD context), the system assigns
each bank credit to a source rail — `razorpay_settlement`, `other_gateway`, `direct_upi`,
`cod_remittance`, or `unrelated` — with a calibrated confidence, and **abstains** (routes to an
exception) rather than guess when evidence is insufficient or ambiguous. This is the entire
differentiator; it is built first and deepest, before anything else is written.

**Why this priority**: Zero of the 261 competing repos do this — they all match. It is the only
thing that makes this project not a worse copy of Razorpay's own product. If only this ships, the
submission is already differentiated.

**Independent Test**: Run attribution on a 20-row commingled sample end-to-end and confirm every
credit is either attributed to a rail with a confidence and an evidence trace, or abstained with a
reason — and that **no credit is ever attributed to `razorpay_settlement` without substantive,
non-coincidental evidence**.

**Acceptance Scenarios**:

1. **Given** a bank credit that exactly matches a Razorpay settlement's identifier, **When**
   attribution runs, **Then** it is attributed `razorpay_settlement` (Tier A: exact) with the
   matching evidence recorded.
2. **Given** a credit whose amount coincidentally equals a Razorpay settlement total but shares no
   identifier and carries a non-Razorpay narration, **When** attribution runs, **Then** it is NOT
   attributed to Razorpay — coincidental amount alone is never sufficient.
3. **Given** a credit whose amount can be satisfied by **more than one** distinct subset of
   settlement legs (set-sum ambiguity), **When** attribution runs, **Then** the system **abstains**
   and records "multiple satisfying subsets" as the reason — it never picks one arbitrarily.
4. **Given** a credit with weak, correlated evidence across amount/time/narration, **When**
   confidence is computed, **Then** correlated signals are NOT treated as independent (no
   noisy-OR overconfidence), and if calibrated confidence is below the abstention threshold the
   credit is abstained.

---

### User Story 2 - Reconcile the proven Razorpay slice and surface recoverable ITC (Priority: P2)

For credits proven `razorpay_settlement`, reconcile each to the paise against the settlement
report (settlement_id is the match key, not UTR), account for the fee and the GST charged on that
fee, and surface the recoverable GST **input tax credit** as a rupee figure — extracted from
Razorpay's own itemized fee+tax, never invented tax logic.

**Why this priority**: This turns proven attribution into a concrete money outcome (recoverable
ITC) and closes one honest loop to the paise. It depends on P1 and only ever operates on the
proven slice.

**Independent Test**: On the sample, confirm the reconciled Razorpay slice balances to the paise
against the settlement report, the ITC figure equals the sum of GST-on-fee across the proven
settlements, and no abstained credit is included.

**Acceptance Scenarios**:

1. **Given** a set of credits proven Razorpay's, **When** reconciliation runs, **Then** each
   reconciles to its settlement to the paise (settlement_id keyed), with fee and GST-on-fee split.
2. **Given** a bank credit that merges many settlement legs into one line, **When** reconciliation
   runs, **Then** the bounded set-sum resolves it only if exactly one leg-subset satisfies the
   total; otherwise it stays an exception.
3. **Given** the reconciled slice, **When** ITC is computed, **Then** the recoverable figure is the
   summed GST-on-fee, each rupee traceable to a settlement; if GST cannot be proven for a line, it
   is omitted, never estimated.

---

### User Story 3 - Honest exception queue with precision-at-coverage, and human-proposed rules (Priority: P3)

Every abstained or unresolved credit appears in an exception queue with a plain reason and its
evidence trace. Results are reported as **precision-at-coverage with an abstention curve** — never
a single bare match rate. When a human resolves an exception, the system may **propose** a durable,
versioned rule capturing that resolution; the rule takes effect only after **human approval** and
never modifies the deterministic core (no self-modification).

**Why this priority**: The abstention story and honest reporting are what make the precision claim
credible; the human-proposed rule is the safe, defensible form of "it learns." Depends on P1/P2.

**Independent Test**: Confirm the report shows precision at multiple coverage levels + the
abstention curve (not one number); resolving one exception produces a *proposed* rule that does
nothing until explicitly approved, and once approved is versioned and attributed to the approver.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the report is produced, **Then** it shows precision at
   several coverage points and the abstention curve, plus the exception list with reasons.
2. **Given** a human resolves an exception, **When** they opt to remember it, **Then** a rule is
   *proposed* (not applied), and only after human approval is it stored, versioned, and applied to
   later runs — a near-but-not-confident match never triggers the rule.
3. **Given** an approved rule, **When** a later run applies it, **Then** the credit is marked
   rule-derived (distinct from deterministically proven) and traceable to the approving human; the
   rule never lowers the precision bar.

---

### Edge Cases

- **Set-sum false match**: with a large candidate pool, multiple unrelated leg-subsets can hit the
  same total by coincidence → **abstain when >1 subset satisfies**; never pick one.
- **Noisy-OR overconfidence**: amount/time/narration evidence is correlated → combine so correlated
  signals do not inflate confidence; the abstention threshold must sit on **calibrated** scores.
- **Coincidental amount**: an amount equal to a settlement total, with no identifier and non-Razorpay
  narration, is never attributed to Razorpay.
- **Incomplete taxonomy**: reversals, sweeps, interest, GST refunds, self-transfers may appear →
  attribute to the correct non-Razorpay class or abstain; never force into Razorpay.
- **GST unprovable**: omit the ITC line rather than estimate.
- **Unbalanced reconciliation**: if a proven set cannot balance to the paise, surface the residual;
  never force a balancing entry.
- **Duplicate / partial / split settlement**: one settlement split across two bank credits, a
  settlement re-credited, or a credit that only partially satisfies a leg → surface as a
  partial/duplicate exception (FR-016); never force or net two credits to balance.
- **Time-order sanity**: a credit dated before its candidate settlement, or outside any plausible
  settlement window, MUST lower confidence or abstain — time is a hard gate, not a soft signal (FR-017).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST attribute each bank credit to a source rail
  (`razorpay_settlement`/`other_gateway`/`direct_upi`/`cod_remittance`/`unrelated`) with a
  calibrated confidence and an evidence trace, or abstain with a reason.
- **FR-002**: System MUST NOT attribute a credit to `razorpay_settlement` on coincidental amount
  alone — a substantive, non-coincidental signal is required: an **exact identifier match** or a
  **unique bounded set-sum**. A narration signal may only raise or lower confidence; it MUST NEVER
  by itself justify a `razorpay_settlement` verdict (consistent with FR-010).
- **FR-003**: System MUST abstain when a credit's amount is satisfiable by more than one **distinct**
  settlement-leg subset (set-sum ambiguity), recording the reason. Two subsets are *distinct* iff
  they contain different sets of settlement_ids. All amount matching is **exact to the paise
  (tolerance 0)** unless a fixture documents specific bank rounding; no fuzzy amount windows.
- **FR-004**: System MUST combine correlated evidence without treating it as independent (no
  noisy-OR overconfidence) and MUST place the abstention threshold on calibrated confidence scores.
- **FR-005**: System MUST reconcile the proven Razorpay slice to the paise using settlement_id as
  the match key, splitting net/fee/GST-on-fee, and MUST never include an abstained credit.
- **FR-006**: System MUST surface recoverable GST input tax credit as the summed GST-on-fee over the
  proven slice, each rupee traceable; MUST omit any line whose GST cannot be proven.
- **FR-007**: System MUST report precision-at-coverage with an abstention curve, never a single
  bare match rate.
- **FR-008**: System MUST place every abstained/unresolved credit in an exception queue with a
  reason and evidence trace.
- **FR-009**: On human resolution, System MUST only *propose* a versioned rule; the rule MUST NOT
  apply until human-approved, MUST never modify the deterministic core, and MUST mark rule-derived
  attributions distinctly and traceably.
- **FR-010**: The attribution core MUST be deterministic; any AI (narration reading) is edge-only,
  off by default, and MUST never be the sole basis for a `razorpay_settlement` verdict.
- **FR-011**: Every attribution, reconciliation, and rule action MUST be recorded in an **append-only,
  hash-chained audit log** sufficient to explain any decision after the fact. (Precise claim, not a
  vague "tamper-evident" — defend it as append-only + hash-chained, nothing more.)
- **FR-012**: The core MUST be rail-agnostic behind a pluggable source adapter (Razorpay is one
  class among several); Razorpay is implemented deepest, other rails sufficiently to attribute.
- **FR-013**: The build MUST produce a **measured AI ablation table** — attribution
  precision-at-coverage/recall with AI on vs off, plus added latency and cost — so the "AI off by
  default" decision is *shown, not asserted*. The "AI adds ~0 marginal recall" claim MUST be backed
  by this table, or it reads as "I couldn't get the AI to work."
- **FR-014**: Because the core is rail-agnostic (FR-012), the system MUST expose a **cross-rail
  comparison** over the merchant's own attributed data — settlement speed and effective cost (bps)
  per rail — a capability structurally impossible for a matching-only pipeline. It is derived from
  existing attribution output (no new data source) and is a demo highlight, not new scope.
- **FR-015**: v1 attributes **inbound credits only**. Debit-side events (settlement reversals,
  sweeps, chargeback debits) MUST be detected and **flagged as out-of-scope debits** — never silently
  ignored or misclassified as a credit rail. Netting a reversal against its prior credit is explicitly
  deferred (roadmap). The report MUST state this credit-only boundary.
- **FR-016**: A settlement_id that maps to **zero** bank credits, or to **more than one** bank credit
  (partial payout, duplicate/re-credit, reversal-then-recredit), MUST be surfaced as an exception with
  a partial/duplicate reason. The system MUST NEVER net two credits together to force a balance.
- **FR-017**: Time is a **hard sanity gate**, not just a soft signal: a credit dated before its
  candidate settlement, or outside any plausible settlement window, MUST lower confidence or abstain.

### Evaluation Requirements (first-class — this is how the edge survives a panel)

- **ER-001**: The `razorpay_settlement` class MUST be built on **real Razorpay settlement records**
  from the test-mode API (real UTR/settlement_id format, real fee/GST breakdown, real timing).
- **ER-002**: Bank-narration grammar MUST be **transcribed from real sources** (published specimen
  statements + surfaced datasets), with a documented mapping table — never invented probabilistically.
- **ER-003**: The scoring test set MUST be generated by a **generator-blind** process, its hash
  frozen, and scored in a **single sealed run**; the reported number MUST be that sealed number,
  never a dev-set number. This sealed set is DISTINCT from the judge-facing demo data (PR-002/SC-006).
  Generator-blindness is enforced structurally: the sealed generator runs from the frozen corruption
  spec only, in a separate process, importing nothing from `engine/` (same isolation as the
  engine/generator rule).
- **ER-004**: Reporting MUST volunteer what the evaluation does and does not establish (adversarial
  stress suite, not a real-world-performance claim), and MUST validate on 2–3 real bank formats
  rather than claiming "every bank."
- **ER-005**: The report MUST state the evaluation's **n** (number of statements / credits /
  merchant-mixes covered) and MUST explicitly **disclaim generalization** beyond that n — no
  universal-performance claim.

### Product-wrapper Requirements (presentation layer — must not bloat the core)

- **PR-001**: A landing page MUST explain the wedge, and a "see it on demo data" path MUST run the
  engine live for judges without any upload.
- **PR-002**: Bundled **demo data** MUST let a judge reproduce the headline result in one click.
- **PR-003**: Default operation MUST be **zero-storage** (files processed in memory/temp, deleted
  after) — this is the privacy moat. Any saved history is optional and stores **derived metadata
  only** (never raw statements) and is marked roadmap.
- **PR-004**: The demo's **primary screen** and the README **headline** MUST lead with the
  **attribution + abstention** result — the count of credits attributed vs abstained (with reasons)
  and the **precision-at-coverage curve**. Reconciliation and recoverable ITC render **below**,
  explicitly labeled "proven slice only." A demo that opens on a match rate or an ITC figure FAILS —
  leading with the abstention story is what makes a judge see the one attribution entry in the field,
  not the ninth matching entry.

### Key Entities

- **Bank Credit**: one inbound credit line; attributes: amount, date, narration, evidence trace,
  attributed rail or abstention + reason, calibrated confidence.
- **Attribution Evidence**: the signals behind a verdict (identifier match, bounded set-sum subset,
  narration signal), with the correlation-aware combination result.
- **Settlement**: a Razorpay settlement record (real test-mode format); attributes: settlement_id,
  UTR, net/fee/GST-on-fee, legs, timing.
- **Exception**: an abstained/unresolved credit with reason + evidence.
- **Proposed Rule / Approved Rule**: a human-authored resolution rule; attributes: matching
  criteria, rail, proposer/approver, version, active state.

## Success Criteria *(mandatory)*

- **SC-001**: The measured **false-attribution rate** for `razorpay_settlement` at the operating
  threshold is reported on the sealed set (by `eval/`, which alone reads ground truth), with every
  false attribution listed. The claim is a measured number with its errors shown — never an
  unfalsifiable "zero".
- **SC-002**: On the **generator-blind sealed set**, `razorpay_settlement` attribution precision is
  reported with its abstention curve; the headline is precision-at-coverage, never a bare rate.
- **SC-003**: Every set-sum resolution has exactly one satisfying leg-subset; whenever >1 subset
  satisfies, the system abstained (verified on the sealed set — **zero forced picks up to a
  candidate pool of N=200 legs**).
- **SC-004**: Confidence is calibrated to a stated bar — **expected calibration error (ECE) ≤ 0.10**
  on the sealed set via a reliability diagram (predicted vs observed) — and the abstention threshold
  sits on that calibrated score.
- **SC-005**: The reconciled Razorpay slice balances to the paise; recoverable ITC equals summed
  GST-on-fee and is fully traceable; no abstained credit is included.
- **SC-006**: A judge can reproduce the **demo** on bundled seeded demo data in one click,
  bit-for-bit reproducible with a fixed seed. This demo data is a DISTINCT artifact from the sealed
  evaluation set (blind, hashed, scored once) that produces the headline metric (SC-002) — the
  headline number never comes from the demo data.
- **SC-007**: Every decision is explainable after the fact from the audit trail.

## Out of Scope (slides, not build)

- Cash forecasting, settlement Q&A agent, Tally/Zoho journal-entry export — presented as roadmap
  slides only, never built for the submission.
- GST **filing** / GSTR data integration — surfacing recoverable ITC is in scope; filing is not
  (a compliance liability in front of Razorpay staff, and attribution does not need it).
- Self-modifying rules — explicitly forbidden; rules are human-proposed and human-approved only.
- "Every bank" parsing — validate 2–3 formats; do not claim universal coverage.

## Assumptions

- The existing deterministic attribution+reconciliation engine, adversarial generator, and eval
  harness are the foundation; this narrows and hardens them, it does not restart.
- Real Razorpay settlement records are obtainable from the test-mode API; narration specimens are
  obtainable from published bank statements + surfaced datasets.
- The builder must defend every component live; nothing enters the build that cannot be explained
  on a whiteboard.

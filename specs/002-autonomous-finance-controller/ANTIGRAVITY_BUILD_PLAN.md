# Antigravity Build Plan — Attribution-First Finance Controller (untangle)

**Audience:** the AI coding agent (Antigravity) that will build this. Read this whole file
before writing any code. Follow it literally. When in doubt, STOP and ask the human — do not
improvise.

**Source-of-truth hierarchy (higher wins on any conflict):**
1. `.specify/memory/constitution.md` (project principles)
2. `specs/002-autonomous-finance-controller/spec.md` (WHAT to build)
3. This file (HOW to build it, in what order, with what guardrails)
4. Existing code in `engine/`, `generator/`, `eval/`, `ui/`, `webapp/`

If any instruction here conflicts with the spec, the spec wins — surface the conflict to the
human instead of guessing.

**External brief used for scope:** [Razorpay AI Buildathon — Track 04: AI Finance
Controller](https://razorpay.com/buildathon/) (verified 2026-09-01). The submission bar is one
finance-operations loop over a batch of at least 50 synthetic records, with throughput, measured
accuracy, and an honest exception list. The larger product roadmap in §10 is not a prerequisite
for submission.

**Numbering rule:** `S1`–`S5` below are Track 04 submission gates. `P1`–`P11` in §10 are long-term
product phases. PR sequence numbers are recorded separately as `W1`, `W2`, ... . Never rename a
product phase to match the order in which a PR happened to land.

---

## 0. Mission (one sentence — memorize it)

> An attribution-first finance controller that **refuses to reconcile money it cannot prove
> belongs to Razorpay**. A false match is worse than no match.

The entire edge is the **attribution module**: assigning each commingled bank credit to its true
source rail, and **abstaining** when it cannot prove the answer. Everything else in the build
exists to make that edge real, measurable, and easy for reviewers to verify.

---

## 1. NON-NEGOTIABLE GUARDRAILS (violating any of these fails the build)

These are hard rails. Do not "improve," relax, or work around them.

- **G1 — Never attribute to `razorpay_settlement` on coincidental amount alone.** A substantive,
  non-coincidental signal is required: **an exact identifier match, or a *unique* bounded set-sum.**
  A narration signal may raise or lower confidence but **MUST NEVER by itself justify a
  `razorpay_settlement` verdict** (this aligns G1 with G4/FR-010 — narration is the AI-read,
  off-by-default channel and can never be the sole basis). Amount equality is never sufficient.
- **G2 — Abstain on set-sum ambiguity.** If more than one **distinct** subset of settlement legs
  sums to the credit amount, ABSTAIN and record "multiple satisfying subsets." Never pick one. Two
  subsets are *distinct* iff they contain **different sets of settlement_ids**. **All amount matching
  is exact to the paise (tolerance 0)** — no fuzzy amount windows — unless a fixture documents
  specific bank rounding.
- **G3 — No noisy-OR overconfidence.** Amount, time, and narration evidence are correlated. Do NOT
  combine them as if independent. The abstention threshold sits on a **calibrated** confidence.
- **G4 — Deterministic core; AI at the edges only, off by default.** No LLM may be the sole basis
  for a `razorpay_settlement` verdict. The core must run and be defensible with AI switched off.
- **G5 — Rules are proposed, never self-applied.** A human resolving an exception may *propose* a
  versioned rule; it does nothing until a human approves it. Never let the system modify its own
  deterministic logic.
- **G6 — No deliberate persistence of raw uploads.** Application code operates on bounded byte
  snapshots and never saves a raw bank statement to a database or durable application storage.
  Framework-managed multipart handling may use ephemeral temporary storage; it must remain bounded
  and be cleaned up on every terminal path. Optional saved history stores derived metadata only and
  is out of scope for the submission build (roadmap). **Audit traces and the FAILURE_LOG MUST store
  derived evidence (identifiers, subset ids, scores) — never verbatim raw statement rows or
  narration strings** (those are the sensitive content).
- **G7 — The engine never reads ground truth.** `engine/` MUST NOT import from `generator/` and
  MUST NOT read any `ground_truth*` file. Only `eval/` may read ground truth. Keep this isolation.
- **G8 — Report precision-at-coverage + abstention curve. Never a single bare "match rate."**
- **G9 — Every decision is auditable.** Attribution, reconciliation, and rule actions all write to
  the tamper-evident audit trail with enough detail to explain the decision later.
- **G10 — Do not build anything in the "Out of Scope" list (§7).** Not "just a little." Slides only.

If you are about to violate a guardrail because it seems to make results better, that is exactly
the situation the guardrail exists for. STOP and ask the human.

---

## 2. SUBMISSION BUILD ORDER (S1–S5; each stage has an acceptance GATE)

Build strictly in this order. Do not scaffold later phases early. Do not build breadth before the
attribution edge is deep and proven.

### S1 — Attribution module, 20 rows end-to-end (THE EDGE)
- **Goal:** attribute a 20-row commingled sample to rails with calibrated confidence + evidence
  trace + abstention. Nothing else gets written until this works.
- **Pinned sample composition (the gate is only real if these are present):** the 20 rows MUST
  include **≥3 set-sum-ambiguous** credits (>1 satisfying subset), **≥2 coincidental-amount** credits
  (amount equals a Razorpay total but no identifier + non-Razorpay narration), **≥2 `unrelated`**,
  and **≥2 that MUST abstain.** Otherwise the gate passes trivially on easy rows and tests nothing.
- **Deliverables:** attribution over the 5 rails; evidence trace per credit; abstention with
  reason; the Tier A (exact) / bounded set-sum / narration-signal evidence path.
- **GATE (all must hold):**
  - Every one of the 20 credits is either attributed (rail + confidence + evidence) or abstained
    (reason).
  - No `razorpay_settlement` verdict rests on coincidental amount alone (G1).
  - A credit with >1 satisfying leg-subset is abstained (G2).
  - Reproducible with a fixed seed.
- **FORBIDDEN this phase:** UI work, reconciliation, ITC, exports, extra rails polish. Attribution only.

### S2 — The two killer analyses (this is what survives the panel)
- **Goal:** prove the two subtle failure modes are handled, with a curve for each.
- **Deliverables:**
  1. **Set-sum false-match curve:** false-match rate vs candidate-set size. Show that as the pool
     grows, coincidental multi-subset collisions rise, and that the system abstains on them
     (curve trends to zero forced picks).
  2. **Noisy-OR reliability diagram:** predicted confidence vs observed accuracy (calibration).
     Show the abstention threshold sits on the calibrated score.
- **GATE (pass/fail, not "reported"):** **ECE ≤ 0.10** on the reliability diagram; **zero forced
  picks across candidate-set sizes up to N=200**; both curves generated from the engine's own output
  (not hand-drawn).

### S3 — Close one loop to the paise (reconciliation + ITC), proven slice only
- **Goal:** reconcile the credits proven Razorpay's, to the paise, and surface recoverable ITC.
- **Deliverables:** settlement_id-keyed reconciliation; net/fee/GST-on-fee split; recoverable ITC
  = summed GST-on-fee, each rupee traceable; abstained credits excluded.
- **GATE:** proven slice balances to the paise; ITC traceable; no abstained credit included;
  unbalanced sets surface a residual instead of forcing a balancing entry.

### S4 — Exception queue + honest reporting + human-proposed rules
- **Goal:** the abstention story, made legible and safe.
- **Deliverables:** exception queue (reason + evidence per item); **precision-at-coverage report +
  abstention curve** (G8); human resolution → *proposed* versioned rule (G5), applied only after
  human approval, marked rule-derived and traceable.
- **GATE:** report shows precision at multiple coverage points + abstention curve (never one
  number); a proposed rule does nothing until approved; approved rule never lowers precision.

### S5 — Evaluation hardening (see §3) + product wrapper (see §4)
- Only after S1–S4 pass their gates.

Do not merge a submission stage whose gate has not passed. If a gate fails, fix it before
proceeding.

---

## 3. EVALUATION PROTOCOL (do this exactly — it is how the edge is defended)

The evaluation must be structurally harder to dismiss than the 8 competing generators already in
the field. Follow all four:

- **E1 — Real Razorpay settlements as the spine.** The `razorpay_settlement` class is built on real
  test-mode Razorpay settlement records (real UTR/settlement_id format, real fee/GST, real timing).
  Not invented. Record provenance.
- **E2 — Transcribed narration grammar.** Do not invent the corruption model. Transcribe narration
  grammar (truncation widths, RRN/UTR placement, VPA rendering) from real sources — published
  specimen statements (HDFC/ICICI/SBI/Axis/Kotak) and the surfaced datasets. Produce a **mapping
  table** documenting source → grammar rule. The claim must be "transcribed from N real sources,"
  never "I wrote a probabilistic script."
- **E3 — Generator-blind sealed holdout.** Write the corruption spec. A separate step/agent that has
  **never seen the matcher** generates the sealed test set. Freeze its hash. Score in **ONE run**.
  Report that number only — never a dev-set number. This directly answers "you solved your own
  puzzle."
- **E4 — Present as stress testing, not proof.** State plainly: "This is an adversarial stress suite,
  not a claim about real-world performance. Here is what it does and does not establish." Validate
  on 2–3 real bank formats; never claim "every bank."

---

## 4. PRODUCT WRAPPER (presentation layer — must NOT bloat the core)

The core engine stays narrow. The wrapper makes it usable and demoable:
- **The demo's PRIMARY screen MUST lead with attribution + abstention** — the count of credits
  attributed vs abstained (with reasons) and the **precision-at-coverage curve**. Reconciliation and
  ITC render **below**, explicitly labeled "proven slice only." **A demo that opens on a match rate
  or an ITC figure FAILS the gate.** This is the single thing that makes a judge see the one
  attribution entry in the field, not the ninth matching entry, in the first ten seconds.
- **Landing page** that states the wedge (§0) and a **"see it on demo data"** path that runs the
  engine live with no upload.
- **Bundled demo data** so a judge reproduces the headline in one click.
- **Upload path** (three files) → live attribution + reconciliation dashboard, with kind, leak-free
  error handling (no server paths, no raw tracebacks).
- **Zero-storage** (G6). Any "save my history" is derived-metadata-only and roadmap, not built.
- Keep the existing premium UI direction; improve usability, don't add feature sprawl. Any new UI
  feature must read off the same proven engine output.

Follow the `frontend-design` skill guidance for any UI work: distinctive, intentional, not
templated; theme-aware; responsive; accessible.

---

## 5. THE TWO KILLER ANALYSES (explicit, because they win or lose the panel)

1. **Set-sum false matches.** With ~200 settlement legs as candidates, multiple unrelated subsets
   can hit the same total by coincidence. Requirement: enumerate satisfying subsets; **if >1,
   abstain.** Amount match is **exact to the paise (tolerance 0)** — see G2; no fuzzy windows.
   Deliver the curve: forced-false-match-rate vs candidate-set size, showing it held at zero because
   the system abstains.
2. **Noisy-OR overconfidence.** Correlated evidence combined as independent inflates confidence.
   Requirement: a correlation-aware combination; deliver the reliability diagram (predicted vs
   observed) proving calibration, with the abstention threshold on the calibrated score.

These two are not optional analyses; they are the defense against the two hardest technical
attacks. Build them in Phase 2 and keep them in the report.

---

## 6. REPORTING RULES

- Headline is **precision-at-coverage with the abstention curve.** Never a single "match rate."
- Always report the **sealed** number (E3), never the dev number.
- Always volunteer the evaluation's limits (E4) before stating results.
- Keep a **`FAILURE_LOG.md`** written *as things break, with real dates* — do not compose it at the
  end. Criterion 4 (failure recovery) is read first by judges; a log written the night before
  reads completely differently from one accreted during the build.

---

## 7. OUT OF SCOPE FOR THE SUBMISSION CRITICAL PATH

- Cash forecasting and a settlement Q&A agent are separate product directions, not requirements
  for this reconciliation loop.
- Do not expand the existing Tally/JSON/CSV export surface unless a submission-blocking defect is
  demonstrated.
- GST **filing** / GSTR integration → surfacing recoverable ITC is in; filing is out.
- Self-modifying rules → forbidden (G5).
- "Every bank" universal parsing → validate 2–3 formats only.
- Any second track. This is Track 04 only.

These may be legitimate post-submission product ideas, but they do not outrank depth, evidence,
and a reliable five-minute judge journey. Breadth generated cheaply by an agent is not evidence of
engineering judgment.

---

## 8. DEFINITION OF DONE

- S1–S4 gates all pass; S5 evaluation (E1–E4) is done and reported.
- Attribution precision reported as precision-at-coverage on the **sealed** set, with abstention +
  calibration curves; zero forced set-sum picks; zero coincidental-amount Razorpay verdicts.
- Reconciled slice balances to the paise; ITC traceable; abstained credits excluded.
- Exception queue + human-proposed/approved versioned rules working, never self-applying.
- Landing + demo-data one-click reproduction; **demo primary screen leads with attribution +
  abstention + precision-at-coverage** (reconciliation/ITC secondary, labeled "proven slice only");
  zero-storage; kind error handling.
- `FAILURE_LOG.md` accreted during the build with real dates.
- Every claim in the README cites a source the human has personally verified (schema claims cite a
  Razorpay fixture; numbers come from the sealed run).
- The human can defend every component on a whiteboard.

---

## 9. WHEN TO STOP AND ASK THE HUMAN

- Any temptation to violate a guardrail (§1) "because results improve."
- Any conflict between this plan and the spec or constitution.
- Any real-data acquisition step (real settlements, real statements) — the human handles data.
- Any new dependency, network call, or persistence mechanism.
- Any scope addition not explicitly listed as in-scope.

Do not resolve these yourself. Surface them.

---

## 10. AUTHORITATIVE PRODUCT ROADMAP (P1–P11)

This is the complete product direction. It is deliberately larger than the Buildathon brief.
Only items marked **submission-critical** may displace work on the S1–S5 gates or the five-minute
demo. The remainder is sequenced for continued engineering after submission or after a panel asks
for deeper productionization.

### Priority definitions

- **Now — submission-critical:** directly proves the Track 04 bar or removes a credible blocker
  from the judge journey.
- **Next — panel-strengthening:** valuable if the submission gate is already green and the change
  is small, evidence-backed, and low-risk.
- **Later — productization:** important for a real deployed financial system, but harmful if rushed
  into the submission.
- **Evidence-blocked:** no implementation until authentic documentation or a sanitized specimen is
  supplied by the human.

### P1 — Real-world bank ingestion

**Purpose:** convert supported native bank exports into canonical `BankCreditLine` records without
guessing.

- Maintain the fail-closed adapter contract and deterministic detection.
- Preserve the canonical model and record adapter/version/normalization provenance.
- Handle verified variations in headers, amounts, dates, BOM/Unicode, multiline narration,
  footers, empty rows, and contradictory values.
- Add each named bank as its own evidence-backed PR with authentic sanitized fixtures.
- Never infer a bank layout from memory, search snippets, or synthetic examples.

**Status:** foundation merged in PR #51; public evidence claims aligned in PR #52. SBI and other
named-bank adapters are **evidence-blocked** pending authentic native exports. Generic CSV remains
the supported ingestion contract.

**Priority:** Next when evidence exists; otherwise do not block submission.

### P2 — Evidence robustness

**Purpose:** keep attribution sound under narration drift and incomplete identifiers.

- Version evidence/narration pattern packs.
- Separate bank normalization from payment-rail evidence.
- Test truncation, Unicode controls, case/separator drift, and damaged references.
- Add explicit `unsupported_format` and `insufficient_evidence` outcomes.
- Measure precision, recall, coverage, and abstention by evidenced input cohort.
- Keep LLM output advisory and proof-gated.

**Status:** core evidence tiers, abstention, calibration, adversarial generation, and sealed
evaluation exist. Per-bank real-format corpora and versioned pattern packs remain.

**Priority:** Next, but only for evidence-backed cases.

### P3 — Real scale and reliability evidence

**Purpose:** prove the complete loop remains bounded, deterministic, and honest as load grows.

- Report full-pipeline runtime, input rows/bytes, candidate density, result counts, report/journal
  time, and memory with the measurement scope named correctly.
- Maintain 1×, 5×, 10×, 25×, and maximum-supported-payload curves where CI/runtime permits.
- Test saturation, 503 admission, total upload deadlines, timeouts, cancellation, exact slot
  ownership, malformed large inputs, and repeated runs.
- Measure process RSS separately from Python `tracemalloc`; never conflate them.

**Status:** maximum-payload suite merged in PR #53. Concurrent saturation, early admission,
immutable snapshots, slow-upload deadline, and slot ownership merged in PR #54. Broader scale
curves, RSS evidence, client cancellation, and repeated-request behaviour remain.

**Priority:** Now only for remaining claims shown in the submission; otherwise Next.

### P4 — Provider portability

**Purpose:** separate the reconciliation model from Razorpay-specific settlement exports.

- Define canonical settlement transactions, batches, fees/taxes, refunds, disputes, reversals,
  adjustments, provider identifiers, validation, and provenance.
- Move current Razorpay parsing behind a `RazorpaySettlementAdapter` without changing results.
- Add a second provider only from authentic documentation or a sanitized export.
- Keep rail classification distinct from transaction-level reconciliation.

**Status:** not started as a formal provider-neutral boundary; Razorpay is the proven deep slice.

**Priority:** Later. A second provider does not improve the Track 04 submission enough to justify
risk without authentic evidence.

### P5 — Multi-period financial correctness

**Purpose:** preserve exact accounting meaning across closes rather than treating every upload as
an isolated batch.

- Specify opening/closing state and the accounting date policy before implementation.
- Cover cross-cycle refunds, delayed settlements, rolling reserves, holds/releases, disputes,
  reversals after close, and carry-forward exceptions.
- Add idempotent reruns, period locking/reopening, corrective journals, and relationships between
  original and amended close certificates.
- Require exact-paise fixtures and double-entry invariants.

**Status:** existing generators cover several cross-cycle cases. `W6`, the 90-day/multi-month
evaluation, is the evaluation foundation only; it does not complete period state, locking,
reopening, or amended closes.

**Priority:** Next as a bounded evaluation; stateful close management is Later.

### P6 — Operational workflow

**Purpose:** support real teams reviewing and resolving exceptions over time.

- Run history; exception ownership/status/comments; approval/rejection; attachments; resolution
  history; search/filtering; run comparison; exportable audit trail.
- Explicit input/result retention policies, tenant isolation, authentication, and role-based
  permissions.

**Status:** exception and investigation outputs exist, but durable collaborative workflow does not.

**Priority:** Later. Persistence changes the privacy, security, and tenancy model and must not be
rushed into the submission.

### P7 — Durable job execution

**Purpose:** move long-running reconciliation from request lifetime to recoverable jobs.

- Job IDs, progress/state transitions, cancellation, retries, idempotency keys, result retrieval,
  expiry, cleanup, worker crash recovery, and queue saturation.
- Prove retries cannot duplicate journals or certificates.

**Status:** bounded `asyncio.to_thread` execution exists; it is intentionally not presented as a
durable queue.

**Priority:** Later.

### P8 — UI completion

**Purpose:** make the proof legible in the exact journey a judge or finance reviewer follows.

- Upload or run demo data; show input validation/adapters; reconcile; show scoped metrics; inspect
  proof packets and honest exceptions; investigate one exception; show corrective entries; export;
  verify a certificate; demonstrate one controlled failure.
- Test accessibility, responsiveness, keyboard use, empty states, and error states.
- Keep attribution, abstention, and precision-at-coverage above the proven-slice reconciliation
  results.

**Status:** landing page, demo path, dashboard, exceptions, exports, and certificate flows exist.
The final five-minute judge journey and accessibility/error-state audit remain.

**Priority:** Now after the evaluation gate is stable. Presentation quality directly affects
whether reviewers understand the technical edge.

### P9 — Security and operations

**Purpose:** make production-readiness claims only when operational evidence supports them.

- Threat model; authentication/authorization; CSRF/CORS/CSP; upload validation; parser/decompression
  bomb defences as formats expand; SSRF/DNS rebinding regression tests; PII-safe logs; metrics;
  SBOM/dependency scanning; secrets, retention/deletion, backup/recovery, deployment, and rollback.

**Status:** request limits, rate/capacity controls, security headers, sandboxing, DNS-rebinding
defences, readiness, SAST, and leak-free errors exist. Identity, persistence-related controls,
runbooks, and full threat modelling remain.

**Priority:** Next for a concise threat model and truthful deployment checklist; Later for controls
that require persistence or tenancy.

### P10 — Evaluation and scientific credibility

**Purpose:** ensure every public metric is reproducible and resistant to benchmark gaming.

- Preserve the sealed holdout; add real-format/OOD cohorts when evidence exists; compare transparent
  baselines; report uncertainty; add mutation/metamorphic tests; keep experiments separate from
  end-to-end claims; publish composition and limitations; prevent generator leakage.
- Reproduce every public metric through one documented command.

**Status:** sealed generator-blind holdout, calibration, candidate-set analysis, uncertainty work,
and explicit limitations exist. Real-format OOD evidence, broader mutation testing, and a single
public reproduction command remain.

**Priority:** Now. This phase maps directly to measured accuracy and honest reporting in Track 04.

### P11 — Final communication

**Purpose:** let reviewers understand, run, question, and verify the system quickly.

- Accurate README; architecture/data-flow/privacy diagrams; threat model; adapter guide; API/MCP
  reference; benchmark methodology; claims/evidence table; deployment runbook; clean-machine
  quickstart; three-minute fallback demo; five-minute primary pitch; longer technical walkthrough.
- Prepare the application answer for “what broke, and how you got out” from the real `FAILURE_LOG`.

**Status:** substantial technical documentation and failure history exist. Final claims sweep,
clean-machine rehearsal, and recorded submission material remain.

**Priority:** Now after the code/evaluation freeze. The application explicitly evaluates the work,
the architecture, and failure recovery—not feature count.

---

## 11. CURRENT EXECUTION LEDGER

This ledger records implementation order without redefining product phases.

| Work item | Product phase | Deliverable | State | Evidence |
|---|---|---|---|---|
| W1 | P1 | Fail-closed bank adapter boundary | Merged | PR #51 |
| W2 | P1/P10 | Public bank-format claims aligned with evidence | Merged | PR #52 |
| W3 | P1 | SBI native adapter | Evidence-blocked | Authentic sanitized SBI export required |
| W4 | P3/P10 | Maximum-payload pipeline stress suite | Merged | PR #53 |
| W5 | P3/P9 | Concurrent saturation and resource ownership | Merged | PR #54 |
| W6 | P5/P10 | 90-day and multi-month evaluation foundation | In progress | Fresh branch from `origin/main` |
| W7 | Cross-phase | Submission exit audit: claims, tests, benchmark, demo, docs | Pending | Starts only after W6 review |

Update this table in the same PR that changes a work item's state. A branch existing locally is not
completion; only reviewed evidence merged into `main` counts as merged.

---

## 12. SCOPE DECISION FOR TRACK 04

The complete P1–P11 roadmap is good product thinking, but implementing all of it before submission
would be overbuilding. Track 04 asks whether one finance-operations loop works across a meaningful
batch and reports throughput, measured accuracy, and unresolved exceptions honestly. Untangle
already closes that loop: bank-credit attribution → proven Razorpay reconciliation → fee/GST →
exceptions/investigation → balanced outputs and audit evidence.

### Must be true before submission

- The full demo runs from a clean checkout on 50+ records.
- Public numbers come from a reproducible labelled evaluation and name their scope.
- Precision, recall/coverage, abstention, throughput, and honest exceptions are visible.
- The proven Razorpay slice balances to the paise.
- One controlled failure is shown and recovered from safely.
- The five-minute story is clear enough that a reviewer sees the attribution/abstention edge in the
  first minute.
- Claims about bank/provider support never exceed fixture evidence.

### Do not delay submission for

- Five native bank adapters without authentic specimens.
- A second settlement provider without authentic documentation.
- Databases, multi-tenancy, RBAC, durable queues, or enterprise workflow.
- Universal bank parsing, cash forecasting, or an additional Buildathon track.
- Refactors that do not improve a measured submission gate.

### Decision rule for every proposed task

Start it before submission only if all answers are **yes**:

1. Does it strengthen the Track 04 bar or remove a demonstrated judge-journey defect?
2. Can it be tested with evidence already available?
3. Can it land as one reviewable PR without weakening existing claims or invariants?
4. Is its value greater than spending the same time on the pitch, clean-machine rehearsal, or
   failure-recovery story?

If any answer is no, record it under the relevant P-phase and defer it.

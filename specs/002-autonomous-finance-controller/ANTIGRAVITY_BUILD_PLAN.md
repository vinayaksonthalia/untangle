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

---

## 0. Mission (one sentence — memorize it)

> An attribution-first finance controller that **refuses to reconcile money it cannot prove
> belongs to Razorpay**. A false match is worse than no match.

The entire edge is the **attribution module**: assigning each commingled bank credit to its true
source rail, and **abstaining** when it cannot prove the answer. 261 competing repos exist; 0 do
this. Everything else in the build exists to make that edge real and impossible to dismiss.

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
- **G6 — Zero-storage by default.** Uploaded files live in memory/temp and are deleted after the
  run. Never write a raw bank statement to disk or a database. Optional saved history stores
  derived metadata only, and is out of scope for the submission build (roadmap). **Audit traces and
  the FAILURE_LOG MUST store derived evidence (identifiers, subset ids, scores) — never verbatim raw
  statement rows or narration strings** (those are the sensitive content).
- **G7 — The engine never reads ground truth.** `engine/` MUST NOT import from `generator/` and
  MUST NOT read any `ground_truth*` file. Only `eval/` may read ground truth. Keep this isolation.
- **G8 — Report precision-at-coverage + abstention curve. Never a single bare "match rate."**
- **G9 — Every decision is auditable.** Attribution, reconciliation, and rule actions all write to
  the tamper-evident audit trail with enough detail to explain the decision later.
- **G10 — Do not build anything in the "Out of Scope" list (§7).** Not "just a little." Slides only.

If you are about to violate a guardrail because it seems to make results better, that is exactly
the situation the guardrail exists for. STOP and ask the human.

---

## 2. BUILD ORDER (phased; each phase has an acceptance GATE — do not start the next phase until the gate passes)

Build strictly in this order. Do not scaffold later phases early. Do not build breadth before the
attribution edge is deep and proven.

### Phase 1 — Attribution module, 20 rows end-to-end (THE EDGE)
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

### Phase 2 — The two killer analyses (this is what survives the panel)
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

### Phase 3 — Close one loop to the paise (reconciliation + ITC), proven slice only
- **Goal:** reconcile the credits proven Razorpay's, to the paise, and surface recoverable ITC.
- **Deliverables:** settlement_id-keyed reconciliation; net/fee/GST-on-fee split; recoverable ITC
  = summed GST-on-fee, each rupee traceable; abstained credits excluded.
- **GATE:** proven slice balances to the paise; ITC traceable; no abstained credit included;
  unbalanced sets surface a residual instead of forcing a balancing entry.

### Phase 4 — Exception queue + honest reporting + human-proposed rules
- **Goal:** the abstention story, made legible and safe.
- **Deliverables:** exception queue (reason + evidence per item); **precision-at-coverage report +
  abstention curve** (G8); human resolution → *proposed* versioned rule (G5), applied only after
  human approval, marked rule-derived and traceable.
- **GATE:** report shows precision at multiple coverage points + abstention curve (never one
  number); a proposed rule does nothing until approved; approved rule never lowers precision.

### Phase 5 — Evaluation hardening (see §3) + product wrapper (see §4)
- Only after Phases 1–4 pass their gates.

Do not merge a phase whose gate has not passed. If a gate fails, fix it before proceeding.

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

## 7. OUT OF SCOPE (build NONE of these — slides only)

- Cash forecasting; settlement Q&A agent; Tally/Zoho journal-entry export → roadmap slides only.
- GST **filing** / GSTR integration → surfacing recoverable ITC is in; filing is out.
- Self-modifying rules → forbidden (G5).
- "Every bank" universal parsing → validate 2–3 formats only.
- Any second track. This is Track 04 only.

If you think one of these would help, it does not. It is how strong builders lose (breadth is what
an AI agent produces cheaply; depth on the edge is what wins).

---

## 8. DEFINITION OF DONE

- Phases 1–4 gates all pass; Phase 5 evaluation (E1–E4) done and reported.
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

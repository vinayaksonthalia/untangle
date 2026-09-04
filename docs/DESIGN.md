# Untangle UI design and copy system

This document is the build reference for Untangle's public pages and product surfaces. It defines
how the product should look, speak, and expose financial evidence. It does not replace the engine or
presentation contracts: the UI renders their decisions and never recomputes money, upgrades evidence,
or hides abstentions.

## 1. Product idea the interface must communicate

Untangle is an **evidence-grade cash-provenance and settlement controller** for a merchant's
commingled bank credits. It attributes credits to their payment rail, reconciles the proven Razorpay
slice to the paise, surfaces recoverable fee GST, investigates supported variances, and produces
balanced accounting output with an independently verifiable audit trail.

The interface should make one promise memorable:

> Close the difficult settlement exceptions with proof, not guesses.

Three supporting ideas may appear after that promise:

1. **Prove the source.** Separate Razorpay settlements from other gateways, direct UPI, COD
   remittances, unrelated credits, and genuinely unknown lines.
2. **Close the money.** Reconcile the proven settlement slice to the paise and expose the exceptions
   that remain.
3. **Hand back evidence.** Show the decision trail, propose balanced corrective vouchers, and let an
   independent verifier check the close certificate.

This framing comes from [STRATEGY.md](STRATEGY.md), [DEMO.md](DEMO.md), and the architecture's
[one-paragraph mental model](ARCHITECTURE.md#the-one-paragraph-mental-model). Use the official Track 4
language—closing a finance-operations loop across a batch, reporting the match rate, and showing
unresolved exceptions—before introducing implementation terms.

## 2. Truth and claim hierarchy

When sources conflict, copy follows this order:

1. Current engine and presentation contracts.
2. Evidence and support matrices, especially [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md).
3. Current measured results in [BENCHMARK.md](BENCHMARK.md), [latency.md](latency.md), and
   [mvp-eval-results.md](mvp-eval-results.md), with their stated scope and date.
4. Product strategy.
5. Research queues and roadmap material, which must never be written as shipped capability.

Never collapse these distinctions:

- **Attribution** identifies a credit's rail; **reconciliation** ties a proven Razorpay credit to
  settlement rows. They are not synonyms.
- **UNKNOWN** is an attribution abstention. **Unexplained** is an investigation result after no
  supported hypothesis closes a variance within tolerance.
- A **corrective voucher** is a balanced proposal. It is never posted, approved, or booked by
  Untangle. See [AGENTIC_INVESTIGATION.md](AGENTIC_INVESTIGATION.md#5-non-negotiable-invariants).
- **Hash-bound** and **cryptographically authenticated** are separate certificate states. Do not call
  either one simply “secure.” See the
  [UI presentation contract](ARCHITECTURE.md#ui-presentation-contract-boundary).
- Generic-schema compatibility is not native bank-format support. Named-bank narration coverage is
  not named-bank file ingestion. Use the six support levels in
  [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md#1-support-level-taxonomy).
- Seeded, sealed, and multi-seed benchmark results are synthetic unless authentic provenance is
  explicitly documented. Never imply validation on arbitrary merchant exports.

## 3. Voice and tone

### Character

Write like a calm finance controller: exact, concise, accountable, and comfortable saying “not
proven.” Prefer plain operational language over AI theatre. Restraint is part of the trust signal;
[DEMO.md](DEMO.md) explicitly instructs the presenter to “speak plainly, no hype.”

### Rules

| Rule | Do | Do not |
|---|---|---|
| Lead with the user's close | “Close settlement exceptions with proof, not guesses.” | “AI-powered multi-agent reconciliation infrastructure.” |
| State the outcome before the mechanism | “91 credits reconciled to the paise.” | “Noisy-OR Tier A/B/C inference completed.” |
| Make uncertainty explicit | “14 credits need evidence.” | “14 matches failed.” |
| Describe recommendations conditionally | “Up to ₹18,400 recoverable if confirmed.” | “₹18,400 is owed to you.” |
| Keep proposals visibly provisional | “Proposed corrective voucher · Not posted” | “Journal entry completed.” |
| Name the evidence | “Exact settlement reference matched.” | “High-confidence AI match.” |
| Separate measured scope | “Seed-42 synthetic benchmark: precision 1.000.” | “100% accurate on bank statements.” |
| Give errors a next action | “The ledger needs an `amount_paise` column. Download the schema.” | “Invalid file.” |
| Use sentence case | “Verify close certificate” | “VERIFY CLOSE CERTIFICATE” |
| Use Indian money conventions | “₹43,200.99 recoverable fee GST” | “43.2K tax savings” when exact values exist |

### Preferred vocabulary

Use these terms consistently:

- **Bank credit**, **payment rail**, **Razorpay settlement**, **settlement report**, **order ledger**.
- **Attributed**, **reconciled**, **abstained**, **needs evidence**, **unexplained**.
- **Evidence**, **reasoning trace**, **candidate checked**, **blocking reason**, **next action**.
- **Expected settlement net**, **bank credit**, **variance**, **residual**.
- **Proposed corrective voucher**, **balanced**, **not posted**.
- **Close certificate**, **verified**, **failed**, **absent**, **legacy**, **hash-bound**,
  **authenticated**.

Avoid “magic,” “perfect,” “guaranteed,” “fully automated books,” “bank-grade,” “native Razorpay
support,” and “AI decided.” Avoid calling every non-match an error; abstention is a first-class safety
outcome ([ARCHITECTURE.md](ARCHITECTURE.md#the-modules-what-each-one-does-and-why-it-exists)).

### Layer copy by reader need

- **First line:** human outcome, no jargon.
- **Second line:** what data was compared and what remains.
- **Detail:** exact evidence, paise arithmetic, configuration provenance, candidate rejections.

This progressive disclosure keeps the first view calm while preserving the negative space required by
[AGENTIC_INVESTIGATION.md](AGENTIC_INVESTIGATION.md#4-evaluated-candidates-the-negative-space).

## 4. Visual design principles

The reference products use different aesthetics but share useful discipline: Stripe opens with one
broad outcome and demonstrates capability through product surfaces; Ramp uses a short value statement
and benefit-led modules; Mercury pairs a restrained headline with an immediate product demo; Brex
leads with “speed and control”; Razorpay groups a broad finance platform into clear product actions.
See the current homepages for [Stripe](https://stripe.com/), [Ramp](https://ramp.com/),
[Mercury](https://mercury.com/), [Brex](https://www.brex.com/), and
[Razorpay](https://razorpay.com/). Untangle should borrow their hierarchy and restraint, not imitate
their visual identity or unsupported claims.

### One hero idea per screen

- Landing: why Untangle exists.
- Dashboard: what closed and what needs attention.
- Investigate: what explains this variance.
- Upload: what inputs are required and how they are handled.
- Verify: whether this close certificate can be trusted.

The primary heading, first metric, and primary action must all reinforce that one idea. Do not place
multiple equal-weight banners, carousels, or competing CTAs above the fold.

### Layout and spacing

- Use a centered application shell with a practical maximum content width of **1200–1280 px**.
- Use an **8 px base rhythm**. Default spacing steps: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Page gutters: 20 px on small screens, 32 px on tablets, 48–64 px on desktop.
- Section spacing: 64 px within product screens; 96–128 px between landing-page chapters.
- Keep reading text to **60–72 characters per line**. Put detail in tables, drawers, or evidence panels.
- Prefer a 12-column desktop grid, 6-column tablet grid, and single-column mobile flow.
- Align currency decimals and tabular columns. Use fixed-width numerals for amounts, percentages,
  hashes, references, and timestamps.
- Cards are for distinct decisions or objects, not for every paragraph. Related metrics should share
  one surface rather than become a wall of tiles.

### Type scale

Use at most three font roles: a restrained display face, a highly legible UI/body face, and a mono
face for machine evidence. Suggested desktop scale:

| Role | Size / line height | Use |
|---|---:|---|
| Display | 56–64 / 1.02 | Landing hero only |
| Page title | 36–44 / 1.10 | One per page |
| Section title | 24–30 / 1.20 | Major sections |
| Card title | 16–18 / 1.35 | Object or decision name |
| Body | 15–16 / 1.55 | Explanations and guidance |
| Label | 12–13 / 1.35 | Metadata; never critical instructions alone |
| Tabular/mono | 12–14 / 1.45 | IDs, hashes, evidence and amounts |

On small screens, reduce the display to 40–44 px and page titles to 30–34 px. Do not solve density by
shrinking operational text below 14 px.

### Colour has one job: meaning

Use a neutral ink-and-paper foundation with one brand accent. Reserve semantic colours:

- **Green:** evidence-verified, reconciled, balanced, or passed—not generic decoration.
- **Amber:** needs evidence, abstained, legacy, or requires review.
- **Red:** verification failed, malformed input, contradictory evidence, or destructive risk.
- **Blue:** neutral information, selected navigation, or primary action.
- **Grey:** absent, unavailable, secondary metadata, and disabled controls.

Never communicate state by colour alone. Pair colour with an icon and explicit text. A confidence score
is not a green-to-red truth meter; show the evidence tier and disposition instead.

### Prefer visual evidence over explanatory prose

- Use a rail-distribution bar to show where credits came from.
- Use a gross → fee → tax → refund → bank-net waterfall for settlement composition.
- Use a two-sided ledger for corrective vouchers, with debit and credit totals visibly equal.
- Use a timeline for investigation steps and candidate rejection.
- Use a compact funnel for total credits → attributed → Razorpay → reconciled → exceptions.
- Use tables when exact values and comparison matter. Charts must retain accessible text equivalents.

Do not invent trend charts when the report has no time-series data. Never recompute financial totals in
the browser; consume the deterministic presentation contract described in
[ARCHITECTURE.md](ARCHITECTURE.md#ui-presentation-contract-boundary).

### Interaction discipline

- One primary action per view; secondary actions are quiet text or outline controls.
- Filters update the existing view; they do not masquerade as navigation.
- Put provenance and raw technical detail in expandable panels, but never hide a failure state.
- Confirm downloads by naming the artifact: “Download Tally XML,” “Download JSON journal,” or
  “Download certificate.”
- Respect keyboard operation, visible focus, reduced motion, semantic headings, labelled controls,
  and a minimum 44 px touch target.
- Motion may clarify a state transition; it must not animate money totals as entertainment.

## 5. Screen copy and content hierarchy

The recommendations below are canonical defaults. Dynamic values must come from the server's
presentation payload; examples must be labelled as examples or synthetic demo data.

### Landing

**Purpose:** explain the hard edge-case problem in seconds and move the visitor into a real sample or
their own files.

**Eyebrow:** `Settlement reconciliation for Indian finance teams`

**Headline:** `Close settlement exceptions with proof, not guesses.`

**Subcopy:** `Untangle separates commingled bank credits by payment rail, reconciles the proven
Razorpay slice to the paise, and returns an auditable exception trail with balanced accounting
output.`

**Primary button:** `Try the sample`

**Secondary button:** `Upload your files`

**Proof strip:** `Deterministic money logic · Explicit abstention · Balanced journal output ·
Independent verification`

**Recommended story order:**

1. A visual of commingled credits becoming proven rails.
2. The hard slice: mangled references, split settlements, cross-cycle refunds, and competing rails.
3. Three steps: **Attribute → Reconcile → Prove**.
4. Product evidence: dashboard, investigation trace, corrective voucher, certificate verification.
5. A clearly labelled synthetic benchmark panel with metric scope and link to methodology.
6. Final CTA: `Run the sample close`.

Do not lead with the “78% tax” or “5% eats 80%” figures unless the UI links to a verified source and
states the conditions. Strategy material is not, by itself, public substantiation. The product can
make the safer and stronger claim—wrong attribution corrupts downstream books—directly from
[STRATEGY.md](STRATEGY.md#1-the-winning-thesis-repositioning).

### Dashboard

**Purpose:** answer “What closed, what is proven, and what needs attention?”

**Page title:** `Settlement close`

**Subcopy:** `A read-only view of attributed credits, reconciled settlements, recoverable fee GST,
and exceptions for this run.`

**Primary action:** `Investigate exceptions`

**Secondary actions:** `Upload new files`, `Download journal`, `Verify certificate`

**Metric labels:**

- `Bank credits`
- `Attributed with evidence`
- `Razorpay credits`
- `Reconciled to the paise`
- `Needs evidence`
- `Recoverable fee GST`

Always place the denominator beside a rate: `91 of 103 Razorpay credits reconciled`. Label benchmark
metrics separately from operational results; operational payloads must not carry client-supplied
evaluation proof.

**Section headings:**

- `Where the money came from`
- `Settlement close status`
- `Exceptions requiring evidence`
- `Accounting output`
- `Proof and provenance`

**Empty states:**

- No exceptions: `No exceptions require review. Every supported variance in this run closed within
  the configured tolerance.`
- No Razorpay attribution: `No Razorpay settlement credits were proven from the supplied evidence.`
- No journal: `No journal is available because no settlement credits were reconciled.`

**Error state:** `This report cannot be displayed safely because its schema is unsupported. Re-run
the reconciliation with a compatible version.`

### Investigate

**Purpose:** show one variance, the hypotheses checked, the supported root cause—or an honest
abstention—and the proposed next accounting action.

**Page title:** `Investigate variance`

**Subcopy:** `Untangle checks deterministic hypotheses against the supplied settlement evidence. It
does not use an LLM to decide the root cause or move money.`

**Summary labels:** `Bank credit`, `Expected settlement net`, `Variance`, `Resolution status`

**Resolved heading:** `Evidence supports: {human root-cause label}`

**Unexplained heading:** `No supported explanation closes this variance`

**Unexplained subcopy:** `Untangle checked the available hypotheses and abstained. No corrective
voucher was drafted.`

**Sections:**

- `Reasoning trace`
- `Candidates checked`
- `Proposed corrective voucher`
- `Recommended next action`

**Candidate states:** `Matched`, `Did not close variance`, `Not enough evidence`, `Not applicable`

**Voucher banner:** `Proposal only · Balanced · Not posted`

**Buttons:** `Review proposed voucher`, `Download investigation`, `Back to exceptions`

Never rename `unexplained` to “failed.” Never hide rejected candidates. Humanize root-cause labels in
headings—“MDR fee drift,” “Cross-cycle refund lag,” “On-hold release,” “Dispute deduction,” “Partial
capture,” “Bank charge or rounding,” “Rolling reserve”—while preserving the exact machine value in
metadata. The taxonomy and journal mappings come from
[EXCEPTION_TAXONOMY.md](EXCEPTION_TAXONOMY.md).

### Upload

**Purpose:** get three valid inputs into reconciliation without overstating privacy or native format
support.

**Page title:** `Reconcile your settlement files`

**Subcopy:** `Provide a bank statement, settlement report, and order ledger in Untangle's supported
schemas. Files are processed by this server for the reconciliation request.`

**Input labels:**

- `Bank statement · CSV`
- `Settlement report · JSON`
- `Order ledger · CSV`

**Supporting labels:** `Required columns`, `Maximum 15 MB`, `Selected file`, `Remove file`

**Primary button:** `Run reconciliation`

**Secondary button:** `Use sample data`

**Schema action:** `View input schemas`

**Empty drop zone:** `Drop a file here or choose from your device`

**Validation errors:**

- `Choose all three files before running reconciliation.`
- `The order ledger is missing the required amount_paise column.`
- `Settlement report row {n} needs both type and entity_id.`
- `{filename} is larger than the 15 MB limit.`
- `This bank-statement layout is not recognized. Convert it to the generic Untangle CSV schema.`

Do not promise that uploads “never touch disk”: multipart handling may use temporary storage. Do not
label raw HDFC, ICICI, SBI, Axis, Kotak, or RBL files as supported; current production support is the
generic adapter described in [INPUT_FORMATS.md](INPUT_FORMATS.md) and
[BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md).

### Verify

**Purpose:** let a reviewer determine whether a close certificate and its attached report are intact
without trusting the dashboard.

**Page title:** `Verify a close certificate`

**Subcopy:** `Check the certificate envelope, report binding, evidence-pack provenance, and
authentication status independently.`

**Primary button:** `Verify certificate`

**Secondary action:** `Choose another certificate`

**Empty state:** `Choose a certificate JSON file to begin. Verification does not change the report or
post accounting entries.`

**Result headings and copy:**

- Verified: `Certificate verified` / `The supplied artifact passed all applicable integrity checks.`
- Failed: `Verification failed` / `Do not rely on this certificate. Review the failed checks below.`
- Legacy: `Legacy certificate` / `The certificate is valid under an older schema, but it does not
  include every current provenance binding.`
- Absent authentication: `Integrity checked; signer authentication absent` / `The report hash is
  bound, but no authenticated signature was verified.`

**Check labels:** `Envelope integrity`, `Attached report hash`, `Evidence pack`, `Configuration`,
`Signer authentication`, `Schema compatibility`

**Failure action:** `Show failure details`

Never turn a partial result into a single green “valid” badge. Preserve the granular states required by
[ARCHITECTURE.md](ARCHITECTURE.md#ui-presentation-contract-boundary).

## 6. Tables, metrics, and evidence components

### Metric cards

Each card has one value, one label, and at most one short qualifier. Use exact INR formatting when the
payload supplies exact paise. Do not animate from zero because it can make audited values look
provisional.

### Status badges

Use noun or past-participle labels: `Reconciled`, `Needs evidence`, `Unexplained`, `Balanced`,
`Verified`, `Failed`, `Legacy`. Avoid vague labels such as `Good`, `Warning`, and `AI confidence`.

### Financial tables

- Keep identifiers left-aligned and amounts right-aligned.
- Show currency once in the header or consistently in every amount; do not mix styles.
- Preserve the sign of variances and explain the direction in adjacent copy.
- Keep totals visually separated with a rule and stronger weight.
- Provide an accessible sort label and announce active filtering.
- Paginate large collections; never imply the visible page is the whole population.

### Evidence panels

An evidence panel should answer:

1. What decision was made?
2. What evidence established it?
3. What alternatives were rejected?
4. What configuration and schema produced it?
5. What can the operator do next?

Do not expose raw bank narrations, account numbers, full UTRs, filesystem paths, or internal line
hashes in public presentation payloads. Follow the scrubbing and opaque-ID rules in
[ARCHITECTURE.md](ARCHITECTURE.md#ui-presentation-contract-boundary).

## 7. Responsive and accessibility acceptance criteria

- At 375 px, the primary action and current status remain visible without horizontal scrolling.
- Tables either preserve critical columns with horizontal scrolling and a visible affordance, or become
  labelled key-value rows. Never silently drop monetary or evidence columns.
- Charts have text summaries and exact-value access.
- Every status has text and iconography in addition to colour.
- Focus order follows visual order; drawers and dialogs return focus to their trigger.
- Error summaries link to the affected field.
- Currency, percentages, dates, hashes, and identifiers remain selectable text.
- Reduced-motion mode removes nonessential transitions.
- Contrast targets WCAG 2.1 AA; critical financial text should exceed the minimum where practical.

## 8. Pre-merge design review checklist

- [ ] Can a first-time visitor explain the product after the hero and one diagram?
- [ ] Does the page have one dominant idea and one primary action?
- [ ] Are operational results separated from synthetic evaluation results?
- [ ] Are attribution, reconciliation, investigation, and verification states named correctly?
- [ ] Is every recommendation conditional and every corrective voucher marked “Not posted”?
- [ ] Are UNKNOWN and unexplained states visible, useful, and free of failure-shaming language?
- [ ] Does every public capability claim meet the evidence level in `BANK_FORMAT_EVIDENCE.md`?
- [ ] Are exact values shown instead of decorative approximations when paise are available?
- [ ] Does semantic colour retain one stable meaning across all screens?
- [ ] Can the flow be completed by keyboard at 375 px, 768 px, and desktop widths?
- [ ] Are raw sensitive inputs absent from public UI payloads and logs?
- [ ] Does the screen still tell the truth when data is absent, malformed, legacy, or unsupported?

## 9. Source index

Product truth and vocabulary were derived from every current document in `docs/`, with the primary
references being [STRATEGY.md](STRATEGY.md), [DEMO.md](DEMO.md),
[ARCHITECTURE.md](ARCHITECTURE.md), [EXCEPTION_TAXONOMY.md](EXCEPTION_TAXONOMY.md),
[AGENTIC_INVESTIGATION.md](AGENTIC_INVESTIGATION.md),
[ACTIVE_RECOVERY.md](ACTIVE_RECOVERY.md), [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md),
[INPUT_FORMATS.md](INPUT_FORMATS.md), [BENCHMARK.md](BENCHMARK.md), and
[QUALITY_GATES.md](QUALITY_GATES.md). Older or explicitly superseded measurements are not promoted
to evergreen UI claims.

External presentation references: [Stripe](https://stripe.com/), [Ramp](https://ramp.com/),
[Mercury](https://mercury.com/), [Brex](https://www.brex.com/), and
[Razorpay](https://razorpay.com/), reviewed 3 September 2026. These references inform hierarchy,
restraint, whitespace, and progressive disclosure only; Untangle's product claims remain governed by
its own evidence documentation.

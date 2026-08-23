# Feature Specification: Multi-Rail Credit Attribution & Razorpay-Slice Reconciliation

**Feature Branch**: `001-multi-rail-attribution`

**Created**: 2026-08-23

**Status**: Draft

**Input**: User description: Untangle — attribute every bank-statement credit to its payment rail, reconcile the Razorpay slice, surface recoverable fee-GST, and report honest exceptions, for an Indian SMB merchant with a commingled multi-rail bank account.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know which bank credits are even Razorpay's (Priority: P1)

A merchant's bank account receives money from many rails at once — Razorpay settlements, a second gateway, direct UPI, COD remittances, loan disbursals, personal transfers. Before anything can be reconciled, the merchant needs to know which credits are Razorpay's. The system reads the bank statement and labels every credit line with its rail, a confidence level, and an evidence trail — and abstains (UNKNOWN) rather than guess when the signal is weak.

**Why this priority**: Every downstream number (reconciliation, recoverable tax credit, exception list) is wrong if attribution is wrong. This is the core capability competitors assume away. It is independently valuable even alone: a merchant who only learns "these 44 credits are not Razorpay, don't expect them in your recon" has already saved hours.

**Independent Test**: Run attribution over a commingled statement; verify each credit gets a rail verdict + evidence, that low-signal lines abstain, and that attribution precision/recall are measured against blind ground truth — reported per rail and per hard-case class, never as a single blended number.

**Acceptance Scenarios**:

1. **Given** a bank statement with Razorpay and non-Razorpay credits, **When** attribution runs, **Then** every credit line receives exactly one verdict (a rail label or UNKNOWN) with an evidence trail naming the signals used.
2. **Given** a Razorpay settlement credit whose narration carries NO brand token (only a bank code + UTR), **When** attribution runs, **Then** it is still correctly attributed via UTR/amount evidence — not missed for lack of the word "Razorpay".
3. **Given** a non-Razorpay credit whose narration superficially resembles a Razorpay one, **When** attribution runs, **Then** it is NOT falsely attributed to Razorpay (or it abstains) — a false positive is treated as worse than an abstention.
4. **Given** a low-signal ambiguous credit, **When** confidence is below the operating threshold, **Then** the system returns UNKNOWN with the reason, rather than a guess.

---

### User Story 2 - Reconcile the Razorpay slice and recover hidden fee-GST (Priority: P2)

Once the Razorpay credits are isolated, the system reconciles only that slice against Razorpay's settlement recon report — matching each bank credit to the exact set of settled transactions it covers — and reports the recoverable fee-GST (input tax credit) in rupees, extracted from Razorpay's own itemized fee and tax figures, not computed by inventing tax logic.

**Why this priority**: This turns attribution into money. The rupee headline ("₹X of input tax credit sitting unclaimed inside commingled credits") is the merchant-facing value. It depends on P1.

**Independent Test**: On the attributed Razorpay slice, verify each credit's amount equals the sum of its covered recon rows to the paise, and that the reported recoverable fee-GST equals the sum of the settlement report's own tax-on-fee figures for the reconciled transactions.

**Acceptance Scenarios**:

1. **Given** a reconciled Razorpay credit, **When** its coverage is reported, **Then** the covered recon rows' net sums to the credit amount to the paise (allowing only labelled rounding drift).
2. **Given** the reconciled slice, **When** recoverable fee-GST is reported, **Then** the figure is the sum of Razorpay's own itemized tax-on-fee values for those transactions, with each contributing transaction traceable.

---

### User Story 3 - See an honest exception list and ask why (Priority: P2)

Every credit the system cannot confidently attribute or reconcile appears in an exception queue with a named reason. The merchant can ask "why is this credit not matched?" and get a full traced explanation.

**Why this priority**: Honesty about what is unresolved is a first-class deliverable, not a failure. A short, well-explained exception list is more trustworthy than a suspicious 100%.

**Independent Test**: Verify every non-auto-resolved credit is in the exception list with a reason drawn from the taxonomy, and that a "why" query returns the evidence trail for that specific line.

**Acceptance Scenarios**:

1. **Given** an adjustment credit with no order id, payment id, or UTR, **When** processed, **Then** it appears in the exception list labelled as a keyless adjustment needing human review — never force-matched.
2. **Given** any credit, **When** the merchant asks why it was (or was not) matched, **Then** the system returns the rail verdict, confidence, evidence, and — if reconciled — the covered transactions.

---

### Edge Cases

- A Razorpay settlement credit with a brand-less narration (bank code + UTR only).
- Two different credits with identical amounts (amount is NOT a unique key).
- A settlement whose UTR is truncated/mangled in the bank narration beyond recovery from the prefix.
- One settlement arriving as two bank credits on different value-dates, each with its own bank UTR but a shared settlement id.
- A batch whose net is non-positive (refund/chargeback heavy) that rolls forward into a later credit.
- A non-Razorpay credit engineered to look Razorpay-ish (decoy) — must not be falsely attributed.
- Real bank statement lacking any stable per-line id (system must derive a stable key, e.g. a row hash).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ingest three artifacts — a bank statement, a Razorpay settlement recon report, and a merchant order ledger — and validate each on load.
- **FR-002**: System MUST assign every bank credit line exactly one attribution verdict: one of the defined rails (razorpay_settlement, other_gateway, direct_upi, cod_remittance, unrelated) or UNKNOWN.
- **FR-003**: Each verdict MUST carry a confidence level and a human-readable evidence trail naming the signals used.
- **FR-004**: System MUST abstain (UNKNOWN) when confidence is below a stated operating threshold; a false positive attribution is treated as more costly than an abstention, and the threshold MUST be justified by a documented cost model, not an arbitrary constant.
- **FR-005**: Attribution decisions MUST be produced by deterministic logic; a language model MAY be used ONLY to interpret ambiguous free-text bank narration, and MUST NOT make the final money-affecting verdict alone.
- **FR-006**: System MUST run end-to-end with the language model fully disabled, and MUST report a no-AI ablation quantifying the model's marginal contribution.
- **FR-007**: System MUST reconcile only the razorpay_settlement-attributed credits against the recon report, reporting for each the exact set of covered settled transactions.
- **FR-008**: System MUST report recoverable fee-GST in rupees, derived solely from the recon report's own itemized fee and tax figures for reconciled transactions, with per-transaction traceability. System MUST NOT compute tax from first principles or assert any tax-eligibility judgment.
- **FR-009**: System MUST produce an exception list of every credit not auto-attributed or not reconciled, each with a reason drawn from the published taxonomy.
- **FR-010**: System MUST answer a bounded set of merchant questions (e.g. "why is this credit not matched?") with a full traced explanation for the specified line.
- **FR-011**: System MUST mask personally identifiable information (names, contact details) before passing any text to a language model.
- **FR-012**: System MUST be read-only toward money: it requests no write/payout capability and cannot move funds.
- **FR-013**: System MUST log every attribution and reconciliation decision to an append-only, tamper-evident record.
- **FR-014**: System MUST NOT read the data generator's source; it consumes only generated data files and the published taxonomy.
- **FR-015**: Evaluation MUST report attribution precision and recall against blind ground truth, broken down per rail AND per hard-case class — never only as a single blended accuracy — and MUST report confidence calibration.
- **FR-016**: The benchmark data the engine is measured on MUST be adversarial: it MUST include brand-less Razorpay credits, colliding amounts, destroyed-prefix UTRs, and Razorpay-looking decoy non-Razorpay credits, so that no single trivial key (brand keyword, unique amount, or clean UTR) can solve attribution.
- **FR-017**: A merchant MUST be able to run the full pipeline and reproduce every reported figure with a single documented command.

### Key Entities *(include if feature involves data)*

- **Bank Credit Line**: one incoming credit on the merchant's statement — amount, value date, narration text, bank reference; the unit being attributed.
- **Recon Row**: one settled Razorpay transaction (payment/refund/transfer/adjustment) with its fee, tax, settlement id, and UTR; the evidence and reconciliation target.
- **Order Ledger Entry**: a merchant-side order record; supporting context, may be missing/mangled/duplicated.
- **Rail Attribution**: the verdict for a bank credit — rail label or UNKNOWN, confidence, and evidence trail.
- **Reconciliation Result**: for a razorpay_settlement credit, the covered set of recon rows and the paise-level balance.
- **Exception**: an unresolved credit with a taxonomy-coded reason.
- **Ground Truth Label**: the blind answer key (true rail + covered rows) used only for evaluation, never visible to the engine.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a batch of many thousands of transactions and hundreds of bank credits, the system reports rupee-denominated results — total attributed, total reconciled to the paise, recoverable fee-GST, and an exception queue — that a reviewer can reproduce exactly from a single command.
- **SC-002**: Attribution precision on razorpay_settlement is high enough that auto-attributed credits are trustworthy, at a stated operating point justified by the documented cost model; precision and recall are reported per rail and per hard-case class.
- **SC-003**: On the hardest cases (brand-less Razorpay lines, colliding amounts, destroyed-prefix UTRs, decoys), recall and precision are reported individually and are non-trivial — i.e. a naive single-key baseline is shown to fail on them while the system does measurably better.
- **SC-004**: The no-AI ablation reports a concrete number for the language model's marginal contribution (which may be small); the system's core result stands with AI disabled.
- **SC-005**: Confidence calibration is demonstrated — the system's stated confidence matches its empirical accuracy within a reported tolerance.
- **SC-006**: Recoverable fee-GST reported equals the sum of the recon report's own tax-on-fee figures for reconciled transactions, verifiable line by line.
- **SC-007**: Zero conservation violations across the batch — no rupee is created or lost; attributed + reconciled + exceptions accounts for every credit.
- **SC-008**: A false "this is Razorpay's" on any decoy or ambiguous line is counted and reported; the system prefers abstention to a wrong attribution.

## Assumptions

- A real merchant's bank statement is likely unavailable (private financial data that cannot be ethically sourced online). The engine is therefore measured on synthetic data grounded in publicly documented bank and payment-rail formats, with sources cited; if a real redacted statement is obtained, it is used as an additional out-of-distribution check, not the primary benchmark.
- The synthetic multi-rail data generator (existing supporting component) produces the engine's inputs and the blind ground truth. Per the audit of that generator, the benchmark it produces MUST be hardened to be adversarial (FR-016) before headline metrics are trusted.
- Currency is INR only; multi-currency is out of scope.
- Moving money, filing GST returns, and live bank/gateway API integration are out of scope.
- The recon report schema follows Razorpay's documented format, verified against committed vendor fixtures.
- The operating threshold for auto-attribution vs abstention is derived from a cost model (cost of a wrong auto-match vs cost of an escalation), not asserted.

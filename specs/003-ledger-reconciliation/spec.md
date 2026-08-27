# Feature Specification: Order-Ledger Reconciliation

**Feature Branch**: `003-ledger-reconciliation`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Make the merchant's order ledger — currently validated but unused — earn its place by cross-checking the proven Razorpay slice and the settlement report against the merchant's own order book, surfacing money-and-booking discrepancies as honest exceptions. Deterministic, precision-first, abstain rather than assert a wrong linkage; never force a link; not a general accounting tool."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Money the merchant is owed but hasn't received (Priority: P1)

A finance owner has orders their own system marks **paid** (money the customer paid), yet no Razorpay
settlement in the bank ever arrived for them. They want that list — it is potentially lost revenue,
a stuck settlement, or a gateway that never paid out — surfaced with evidence, so they can chase it.

**Why this priority**: This is the single most valuable output — it points at *real money the merchant
may be losing*. It is the reason the third file (the order ledger) earns its place, and it is a pain no
gateway-side reconciliation tool addresses (they only see their own successes).

**Independent Test**: Run the pipeline on a batch whose order ledger contains paid orders with no
corresponding Razorpay settlement; verify each is surfaced as an "uncredited order" exception with the
order id, amount, and the reason it could not be tied to a settlement — and that a paid order which *is*
covered by a reconciled settlement is NOT surfaced.

**Acceptance Scenarios**:

1. **Given** an order marked paid in the ledger and no settlement in the recon report covering it, **When** the batch is reconciled, **Then** it appears as an `uncredited_order` exception with order id, amount, and a suggested action (verify against the gateway settlement report).
2. **Given** a paid order that IS covered by a reconciled Razorpay settlement, **When** the batch is reconciled, **Then** it does NOT appear as an exception.
3. **Given** the amount owed cannot be linked to exactly one settlement (ambiguous), **When** reconciled, **Then** the tool abstains from asserting a link and surfaces it for human review rather than guessing.

---

### User Story 2 - A settlement whose orders are missing or mis-booked in the merchant's books (Priority: P2)

A settlement arrived and reconciled to the paise, but when checked against the merchant's order ledger,
one or more of its constituent orders are absent, or present with a status that contradicts the
settlement (e.g. the ledger says "pending" or "failed" for money that provably settled). The finance
owner wants these booking errors flagged so the books match reality.

**Why this priority**: Turns the proven Razorpay slice into a books-integrity check — high value, but
secondary to finding missing money because a mis-booked-but-received order is an accounting nuisance,
not lost revenue.

**Independent Test**: Run on a batch with a reconciled settlement whose orders are missing from / in a
contradictory status in the ledger; verify each surfaces as a `ledger_mismatch` exception naming the
settlement, the order id, and the specific mismatch (missing vs status conflict).

**Acceptance Scenarios**:

1. **Given** a reconciled settlement referencing an order absent from the ledger, **When** reconciled, **Then** a `ledger_mismatch` exception names the settlement and the missing order.
2. **Given** a reconciled settlement whose order is in the ledger but with a status contradicting a completed settlement, **When** reconciled, **Then** a `ledger_mismatch` exception states the observed vs expected status.
3. **Given** an order the ledger records twice (duplicate booking) that maps to a single settled payment, **When** reconciled, **Then** a `duplicate_order_booking` exception surfaces both ledger rows.

---

### User Story 3 - Refunds and chargebacks not reflected in the books (Priority: P3)

A settlement includes a refund or a disputed (chargeback) amount, but the merchant's order ledger still
shows the order as fully paid with no refund/dispute noted. The finance owner wants these surfaced so a
refund isn't silently double-counted as revenue.

**Why this priority**: Real but narrower; refunds/chargebacks are a smaller share of volume and the
consequence (slightly overstated revenue) is less urgent than missing money or a mis-booked order.

**Independent Test**: Run on a batch where the settlement carries a refund/dispute the ledger does not
reflect; verify a `refund_not_reflected` exception surfaces the order, the refunded/disputed amount, and
the suggested correction.

**Acceptance Scenarios**:

1. **Given** a settlement carrying a refund for an order the ledger still marks fully paid, **When** reconciled, **Then** a `refund_not_reflected` exception surfaces the order and the refunded amount.

---

### Edge Cases

- **No order ledger, or an empty one**: the feature contributes zero exceptions and never blocks the run; the existing attribution/reconciliation output is unchanged.
- **Order id present in the settlement report but not the ledger, AND vice-versa**: each direction produces its own distinct exception class; neither is silently dropped.
- **Amount agreement but id mismatch (or id agreement but amount mismatch)**: treated as ambiguous — the tool abstains from asserting the link and surfaces it for review rather than force-matching.
- **A ledger status the tool does not recognise**: treated as "unknown status," never silently assumed to be paid or failed.
- **Currency/precision**: all comparisons are to the exact paise; a sub-paise or rounding difference beyond the labelled tolerance is surfaced, never absorbed.
- **Duplicate order ids in the ledger**: surfaced as a duplicate-booking exception, never de-duplicated silently.
- **This feature must never change an attribution or reconciliation verdict** — it only adds a new, separable class of ledger exceptions on top of the existing proven slice.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST use the order ledger as a real input to reconciliation — cross-checking it against the proven Razorpay slice and the settlement report — so that providing the ledger changes the output.
- **FR-002**: The system MUST surface every order marked paid in the ledger that cannot be tied to a reconciled Razorpay settlement as an `uncredited_order` exception, with order id, amount, value/booking date, the reason it could not be tied, and a concrete suggested action.
- **FR-003**: The system MUST surface every reconciled settlement whose constituent orders are missing from, or in a status contradicting, the merchant's ledger as a `ledger_mismatch` exception naming the settlement, the order, and the specific mismatch.
- **FR-004**: The system MUST surface duplicate order bookings and refunds/chargebacks not reflected in the ledger as their own distinct exception classes.
- **FR-005**: The system MUST NOT assert a link between an order and a settlement unless that link is provable to the exact paise on a shared identifier; when a link is ambiguous or only partially supported, it MUST abstain and surface the item for human review rather than force-match.
- **FR-006**: Every ledger exception MUST carry a reason code, a human-readable detail, an evidence trace (the specific ledger row(s) and settlement/recon reference(s) compared), and a suggested next action — the same honesty bar as the existing exception queue.
- **FR-007**: The feature MUST NOT alter any attribution or reconciliation verdict; it only adds a separable class of ledger exceptions, and the run's precision/recall/reconciled numbers MUST be unchanged by turning this feature on.
- **FR-008**: The feature MUST be resilient to a missing, empty, or partially-populated order ledger — contributing zero exceptions and never erroring — since not every merchant supplies a clean ledger.
- **FR-009**: All comparisons MUST be deterministic and reproducible: the same three files produce the same ledger exceptions on every run.
- **FR-010**: The results view MUST present the ledger exceptions clearly alongside the existing exception queue, grouped by reason, so a finance owner can see "money owed" and "books to fix" at a glance.
- **FR-011**: The feature MUST NOT move money, write to the ledger, or take any irreversible action; it only reports discrepancies for a human to act on.
- **FR-012**: The scope MUST stay bounded to order↔settlement discrepancy detection; it MUST NOT become a general-ledger, journal-entry, or tax-filing accounting tool.

### Key Entities *(include if feature involves data)*

- **Order (ledger row)**: a line in the merchant's own order book — an order identifier, an amount, a status (e.g. paid / pending / failed / refunded), and a date. Represents what the merchant *believes* happened.
- **Settlement (from the recon report)**: a settled Razorpay transaction and the orders it comprises — the source of truth for what *actually* settled to the bank. Already reconciled by the existing engine.
- **Ledger Exception**: a discrepancy between the two — its reason code (e.g. `uncredited_order`, `ledger_mismatch`, `duplicate_order_booking`, `refund_not_reflected`), the specific evidence compared, and a suggested action. It is advisory, never a money action.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a batch containing planted discrepancies, the feature surfaces 100% of the paid-but-uncredited orders and 100% of the missing/mis-booked settlement orders, with zero false links asserted (it abstains on ambiguity instead of guessing).
- **SC-002**: Providing the order ledger measurably changes the output — at least one new, correct ledger exception appears that was not present without it — proving the third file now earns its place.
- **SC-003**: Turning the feature on leaves the existing attribution precision, recall, reconciled-slice count, and recoverable fee-GST numbers exactly unchanged (the feature is additive and never corrupts the proven slice).
- **SC-004**: A finance owner can, from the results view, identify the total rupee value of "money marked paid but not yet seen as settled" in under 30 seconds.
- **SC-005**: The feature runs to completion (contributing zero exceptions, no error) when the order ledger is absent or empty.

## Assumptions

- The order ledger shares a join key with the settlement report (an order identifier appears in both); where it does not, the item is surfaced as un-linkable rather than assumed matched.
- "Paid" (and equivalent) ledger statuses indicate the merchant believes the money was received; the exact recognised status vocabulary is small and documented, and any unrecognised status is treated as unknown.
- The recon report remains the source of truth for what actually settled; the ledger is the merchant's belief, and discrepancies are reported in the merchant's favour of caution (surface, don't assume).
- Amounts in all three files are integer paise after ingestion, compared to the exact paise within the same labelled rounding tolerance the reconciliation engine already uses.
- This feature builds on the existing proven-Razorpay slice and exception framework; it reuses their evidence/traceability conventions rather than inventing a parallel one.
- Scope is v1 order↔settlement discrepancy detection only; multi-currency, partial-capture accounting, and journal posting are explicitly out of scope.

---

## Design revision (post-implementation review, 2026-08-27)

Four rounds of adversarial review (gpt-5.6-sol) refined the design without changing its intent:

- **`uncredited_order` was dropped.** From these three files the engine cannot honestly claim
  "Razorpay owes you for this order" — an order absent from Razorpay's recon report is simply not
  Razorpay's (another rail), so flagging it as an uncredited *Razorpay* discrepancy would be a false
  Razorpay signal. The genuine value is in the books-integrity classes below. (US1's "money owed"
  goal is not provable from this input and is retired; the recon-report-backed classes remain.)
- **Outputs are AGGREGATED** — one summary `ExceptionRecord` per class (count, distinct-order total,
  examples), never one row per order — so the exception queue stays short and honest (Constitution V).
- **All checks are scoped to the PROVEN (balanced) reconciled slice** and to orders with a covered
  *payment* row; refund/dispute-only rows never make an order "settled". A doubly-booked order is
  reported only as a duplicate and abstains on status/amount. `(type, entity_id)` keys that resolve
  to materially conflicting rows are excluded (abstain) rather than resolved arbitrarily.

Final classes: `ledger_mismatch`, `duplicate_order_booking`, `refund_not_reflected`.

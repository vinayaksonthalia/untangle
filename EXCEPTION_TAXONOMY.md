# Exception Taxonomy — v0.1 (DRAFT, pre-matcher)

**Status:** written BEFORE any matcher code exists. To be frozen in a tagged commit (`taxonomy-v1`) once merchant interviews land. Incidence rates are NOT statistical estimates — see "Mix policy" below.

**Provenance rule:** every class below cites either (a) Razorpay's own published fixture/docs, or (b) a named merchant interview. Nothing is invented for convenience.

## A. Vendor-derived classes (evidence: razorpay/razorpay-node `documents/settlement.md`, recon response)

| ID | Class | Evidence | Why it can't be ID-matched |
|---|---|---|---|
| V1 | **Adjustment rows** (`entity_id: adj_*`) | Fixture row 4: `order_id: null`, `payment_id: null`, `settlement_utr: null`, `description: "test reason"` | No join key of any kind exists. Must be explained from free-text `description` + amount + timing. |
| V2 | **Route transfer rows** (`trf_*`) | Fixture row 3: `order_id: null`, `method: null`, has `payment_id` | Order ledger has no counterpart; must resolve via parent payment. |
| V3 | **ID location differs by row type — documented, not discovered** | Docs field description, verbatim: `payment_id` is "The unique identifier of the payment linked to `refund` or `transfer` that has been settled… It is `null` for `payments`." Fixture confirms: payment row's `pay_*` id sits in `entity_id` | Tier 1 keys off `(type, entity_id)`, never `payment_id`. The naive join silently drops every payment row — this is failure case #1 in the test suite. **Present as correct handling, never as a discovery: it is in the field description.** |
| V4 | **Sample data is geo-templated — infer no fee/tax semantics from it** | Fetched `…/fetch-recon?preferred-country=IN` and `…?preferred-country=US` and diffed: amounts are byte-identical across variants (payment `fee 2900, tax 0`; transfer `fee 296, tax 46`); only `currency` (INR↔USD) and `card_network` (MasterCard↔AMEX) change | `tax` is documented as "the tax on the fee"; transfer row `debit 100296 = amount 100000 + fee 296` (not +tax) proves tax is **inside** fee — one consistent semantic. The `tax: 0` on the payment row is placeholder sample data, NOT a second semantic. **Do not claim a schema inconsistency here.** INR production semantics to be confirmed against a real merchant recon report. |
| V9 | **`notes` type mismatch** | Docs declare `notes` as type `object`; sample value is the string `"Beam me up Scotty."`; SDK fixture carries `"notes": "{}"` (string) | Strict typed parsing fails on a real field. Parser must accept string-or-object-or-null. |
| V10 | **Vendor sources disagree on `credit_type`** | Docs page shows `credit_type: "default"` on all four rows; `razorpay-node` fixture omits it on the `adjustment` row | Validate leniently; do not require the field. (Weaker than V9 — sources disagree, no production evidence.) |
| V5 | **Cross-cycle refunds** | Fixture row 2: refund `debit` populated, `credit: 0`, settled in a settlement whose payments are from an earlier cycle | Refund lands in a later batch than its original payment; naive per-batch balancing fails. |
| V6 | **Partial settlements** | Razorpay docs: settlement is split when the amount requiring settlement exceeds live balance | One logical settlement → two credits, different days. |
| V7 | **On-hold rows** (`on_hold: true`, `settled: false`) | Fixture field `on_hold` | Money in the report that never arrives in the bank this cycle. |
| V8 | **Dispute-linked rows** (`dispute_id` populated) | Fixture field `dispute_id` | Chargeback reversal, may debit a later settlement. |

## B. Bank-side classes (to be evidenced by merchant interviews + one real redacted statement)

| ID | Class | Status |
|---|---|---|
| B1 | Truncated/mangled UTR in bank narration | NEEDS EVIDENCE — target: real statement |
| B2 | Commingled non-Razorpay credits (Amazon/Flipkart/Meesho payouts, COD remittances) in the same account | NEEDS EVIDENCE |
| B3 | Two settlements landing as one bank credit same day | NEEDS EVIDENCE |
| B4 | Bank charges / reversal lines interleaved | NEEDS EVIDENCE |

## C. Merchant-ledger classes (to be evidenced by interviews)

| ID | Class | Status |
|---|---|---|
| M1 | Missing/mangled `order_id` from platform export (Shopify/Tally/WooCommerce) | NEEDS EVIDENCE |
| M2 | Duplicate order IDs | NEEDS EVIDENCE |
| M3 | Multi-gateway merchant (Razorpay + PayU + Cashfree in one ledger) | NEEDS EVIDENCE |
| M4 | Paise rounding cascades | NEEDS EVIDENCE |

## Mix policy (answers "n=5 isn't a statistic")

We do **not** claim population incidence rates. We report:
1. **Per-class precision and recall** — independent of mix.
2. **Aggregate under three named mixes:** `interview-derived` (from n=5, verticals named), `uniform`, `adversarial-heavy`.

Headline form: *"94% under interview-derived mix, 81% under adversarial mix"* — the sensitivity IS the result.

## Isolation protocol (protects every number we report)

1. Generator is built in a **separate session and repo**, frozen and tagged before the matcher exists.
2. The matcher session **never has generator source in context** — only its output files and this published taxonomy.
3. At least one **out-of-distribution input**: a real redacted bank statement + the merchant's own recon report as ground truth.
4. Labels are written **blind** (before running the system), committed with a hash, never edited. Post-hoc disagreements are adjudicated in writing; we report pre- and post-adjudication numbers and the count of labels changed.

This protocol is stated in the README so "how do I know your matcher wasn't fit to your generator?" has a process answer, not a promise.

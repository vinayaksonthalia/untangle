# Safety & guarantees

untangle is a **read-only reconciliation controller**. It reads statements and settlement
reports, proves what it can, abstains on what it cannot, and hands back evidence. It never
moves money and never posts to your books. This page states what is guaranteed today, and
what is explicitly not, so nothing here is taken on trust.

## Guarantees (in place today)

- ✅ **Read-only toward money.** untangle ingests bank statements, Razorpay settlement reports,
  and order ledgers. It has **no code path** to initiate, authorise, or approve a transfer,
  debit, or payout. There are no banking write credentials anywhere in the system.
- ✅ **No money movement, no posting.** Corrective journal entries are **proposals only** —
  balanced double-entry drafts, clearly marked "not posted." A human reviews and posts them in
  their own accounting system. untangle never writes to a ledger.
- ✅ **Abstain rather than guess.** When the evidence does not prove a link (e.g. two settlement
  candidates match an amount but neither carries a distinct UTR), untangle **refuses to match**
  and surfaces the item for review. Precision is a financial safeguard: a wrong "Razorpay" call
  can corrupt downstream books and, in India, attract punitive tax on an unexplained credit.
- ✅ **Every verdict is evidence-backed.** Each attribution and reconciliation carries the
  signals that produced it. The LLM (when used) only *narrates*; the numbers and the decision
  are computed by deterministic rules.
- ✅ **Deterministic & reproducible.** Same inputs → byte-identical outputs. Money is exact
  integer paise (no floating-point drift). A run is identified by an audit-root hash.
- ✅ **Independently verifiable.** Every close ships a certificate carrying the content
  SHA-256, the report binding, and the per-packet proof checks — re-derive the hash and re-run
  the checks yourself (web `/verify`, the CLI, or by hand). When a signing key is configured the
  certificate is ECDSA P-256 signed; otherwise it is hash-bound (tamper-evident but unsigned) —
  and we say so, never flattening the two into "secure."
- ✅ **Privacy by construction.** Uploaded files are processed **in memory** and discarded when
  the request/session ends. There is **no application database** storing your statements. A
  large upload may be briefly spooled to a temporary file by the server, which is removed when
  the request ends. Nothing is sent to a third party.
- ✅ **Hardened web surface.** A strict Content-Security-Policy (`default-src 'self'`) blocks
  external scripts, fonts, and images; all assets are self-hosted.

## Not guaranteed / explicitly out of scope (☐ = not claimed)

- ☐ **Not a certified system.** No SOC 2, ISO 27001, or statutory certification is claimed.
- ☐ **Not statutory sign-off.** The certificate attests internal mathematical and cryptographic
  consistency. It does **not** replace a statutory audit or transfer accounting responsibility.
- ☐ **Not native bank-format ingestion (yet).** Today untangle ingests its generic CSV/JSON
  schemas; dedicated per-bank export adapters (HDFC/ICICI/SBI/Axis/Kotak/RBL) are planned, not
  shipped — see `docs/BANK_FORMAT_EVIDENCE.md`.
- ☐ **Benchmarks are synthetic** unless a real dataset is explicitly named. Seeded / sealed /
  multi-seed results are on generated data with stated scope; we never imply validation on
  arbitrary merchant exports.

## Reporting

Found something that overclaims, or a way to make untangle assert a match it can't prove?
That is the bug we care about most — open an issue.

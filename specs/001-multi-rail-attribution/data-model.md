# Phase 1 Data Model — Multi-Rail Credit Attribution

All money in integer paise. All types are plain, serializable records (dataclasses).

## BankCreditLine (input, one per credit)
- `key: str` — stable content hash of (value_date, amount_paise, narration, bank_ref); NOT the generator's line_id.
- `value_date: date`
- `amount_paise: int`
- `narration: str` — free text (may contain a UTR-shaped token, brand token, or neither).
- `bank_ref: str | None` — bank's own txn ref (may be a UTR, a mangled UTR, or absent).
- Never carries a rail label — that is the engine's job.

## ReconRow (input, one per settled Razorpay txn)
- `entity_id: str` (pay_/rfnd_/trf_/adj_) — the id; **join key with `type`, never `payment_id`**.
- `type: {payment,refund,transfer,adjustment}`
- `amount_paise, fee_paise, tax_paise: int` — `tax` is GST-on-fee, inside `fee`; net = credit − debit.
- `debit_paise, credit_paise: int`
- `settlement_id: str | None`, `settlement_utr: str | None`
- `settled_at, created_at: datetime`, `on_hold: bool`, `dispute_id: str | None`
- `order_id: str | None`, `method, card_network, card_type, card_issuer: str | None` (null for upi/nb/wallet & adj/trf).

## OrderLedgerEntry (input, supporting; may be dirty)
- `order_id: str | None` (missing/mangled/duplicated in the wild), `amount_paise: int`, `status: str`, `created_at: datetime`.

## RailAttribution (output, one per BankCreditLine)
- `line_key: str`
- `rail: {razorpay_settlement, other_gateway, direct_upi, cod_remittance, unrelated, UNKNOWN}`
- `confidence: float` (0..1)
- `tier: {A,B,C,LLM,none}` — which stage decided it.
- `evidence: list[EvidenceItem]` — human-readable signals with weights.
- `abstained: bool` — true when below τ (rail set to UNKNOWN).
- `llm_used: bool` — true if the narration tier was consulted (for ablation accounting).

### EvidenceItem
- `signal: str` (e.g. "utr_exact", "narration_pattern:cashfree", "amount_corr", "value_date_proximity", "setsum_cover")
- `detail: str`, `weight: float`

## ReconciliationResult (output, one per razorpay_settlement credit)
- `line_key: str`
- `covered_entity_ids: list[str]` — the exact recon rows this credit covers.
- `covered_net_paise: int`, `credit_amount_paise: int`, `residual_paise: int` (0 except labelled rounding drift).
- `balanced: bool`.

## FeeGstRecovery (output, aggregate + per-txn)
- `total_recoverable_paise: int` — Σ recon `tax_paise` over reconciled txns.
- `by_entity: list[(entity_id, tax_paise)]` — traceable.

## Exception (output, one per unresolved credit)
- `line_key: str`, `reason_code: str` (from EXCEPTION_TAXONOMY), `detail: str`, `suggested_action: str`.

## GroundTruthLabel (EVAL ONLY — never loaded by engine)
- `line_key: str`, `true_rail: str`, `true_covered_entity_ids: list[str]`, `hard_case_tags: list[str]`.

## RunReport (top-level output)
- `totals`: attributed/abstained/reconciled/exceptions counts + rupee sums.
- `fee_gst`: FeeGstRecovery.
- `audit_root: str` — hash-chain head.
- `config`: seed, provider/model (or `none`), τ, versions.

## Relationships
BankCreditLine —1:1→ RailAttribution. A razorpay_settlement RailAttribution —1:1→ ReconciliationResult —1:N→ covered ReconRows. Non-resolved BankCreditLine —1:1→ Exception. GroundTruthLabel —1:1→ BankCreditLine (eval join on `line_key`).

## Conservation invariants (property tests)
1. Every BankCreditLine has exactly one of {RailAttribution auto-resolved, Exception}.
2. Σ(reconciled credit amounts) + Σ(exception amounts) + Σ(non-rzp attributed amounts) = Σ(all credit amounts). No rupee created or lost.
3. No ReconRow appears in two ReconciliationResults (no double-cover).
4. Re-running on identical input + `--no-ai` yields byte-identical RunReport.

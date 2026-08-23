# Phase 1 Contract — CLI & Reports

The engine's public interface is a CLI producing deterministic JSON + console reports.

## `untangle run`
Attribute → reconcile → report over one batch.

```
python -m engine.cli run \
  --bank data/bank_statement.csv \
  --recon data/recon_report.json \
  --ledger data/order_ledger.csv \
  --out out/ \
  [--no-ai] [--provider openrouter|gemini|groq|cerebras] [--model <id>] \
  [--threshold <float>] [--seed <int>]
```
- Reads only the three input files + `EXCEPTION_TAXONOMY.md`. Never reads `data/ground_truth.json`.
- `--no-ai`: deterministic path only (must be byte-identical across runs).
- Secrets come from `.env` (never flags/args).
- **Exit codes**: 0 success; 2 input/validation error (clear message: what/why/how to fix); 3 config error (e.g. AI requested but no key). Never a bare stack trace.

### Output: `out/report.json` (schema = RunReport, see data-model.md)
Plus human console summary:
```
Attributed 293 credits: 113 razorpay · 138 other-rail · 42 UNKNOWN (abstained)
Reconciled ₹XX,XX,XXX across 113 credits to the paise · 0 conservation breaks
Recoverable fee-GST: ₹XX,XXX (traceable, from Razorpay's own tax-on-fee)
Exceptions: 42 (by reason: keyless_adjustment 8, ambiguous_narration 19, ...)
Audit root: <hash>
```

## `untangle why <line_key>`
Traced explanation for one credit (User Story 3).
```
python -m engine.cli why <line_key> --out out/
```
Prints: rail verdict, confidence, tier, every EvidenceItem, and — if reconciled — the covered entity_ids and the paise balance.

## `untangle eval` (eval harness — the only component allowed to read ground truth)
```
python -m eval.harness --run out/report.json --truth data/ground_truth.json [--ablation]
```
Reports:
- Attribution **precision & recall per rail AND per hard-case class** (never a single blended number).
- Confidence **calibration** (reliability bins: stated confidence vs empirical accuracy).
- False-positive rate on decoy classes (a wrong "razorpay" is counted explicitly).
- With `--ablation`: runs the batch with and without AI and reports the delta (the LLM's marginal contribution) + LLM cost per 1,000 rows + p50/p95 latency.
- Conservation check: PASS/FAIL on the invariants in data-model.md.

## Guarantees
- Deterministic: `run --no-ai` + `eval` produce identical numbers for identical inputs/seed.
- Isolation: `engine/` imports nothing from `generator/`; `eval/` is the sole reader of ground truth.
- Read-only toward money: no command has any write/payout capability.

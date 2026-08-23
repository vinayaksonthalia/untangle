# Quickstart — Validate untangle end-to-end

Proves the feature works on a generated batch. ~2 minutes, no keys needed for the core path.

## Prerequisites
- Python 3.12+
- Repo cloned; run from repo root.
- (Optional) LLM keys in `.env` — only for the AI narration tier and the ablation. The core deterministic path needs none.

## 1. Generate the benchmark (blind ground truth included)
```bash
python3 -m generator.generate --seed 42 --scale 1.0 --out data
```
Expect: `selfcheck : PASS` and byte-identical files across runs.

## 2. Confirm the benchmark is adversarial (sanity, not the product)
```bash
python3 -m generator.difficulty_probe
```
Expect: each naive single-key baseline is ~100% on the easy majority but collapses on its blind hard-case class. This is the proof no trivial key solves attribution.

## 3. Run the engine (deterministic, no AI)
```bash
python3 -m engine.cli run --bank data/bank_statement.csv --recon data/recon_report.json \
  --ledger data/order_ledger.csv --out out/ --no-ai --seed 42
```
Expect: console summary (attributed / reconciled to the paise / recoverable fee-GST / exceptions / audit root); `out/report.json` written; re-running yields a byte-identical report.

## 4. Score it against blind ground truth
```bash
python3 -m eval.harness --run out/report.json --truth data/ground_truth.json
```
Expect: precision/recall **per rail and per hard-case class**, calibration bins, decoy false-positive rate, and a conservation check = PASS. Success = high precision on razorpay_settlement with abstention on the genuinely ambiguous tail, and non-trivial recall on the hard classes where the naive baselines failed in step 2.

## 5. Ablation — what the AI actually adds (needs an LLM key in `.env`)
```bash
python3 -m eval.harness --run out/report.json --truth data/ground_truth.json --ablation
```
Expect: a concrete delta (AI-on vs AI-off) — possibly small — plus LLM cost per 1,000 rows and p50/p95 latency. The core result must stand with AI disabled.

## 6. Explain one credit (the "why" trace)
```bash
python3 -m engine.cli why <line_key> --out out/
```
Expect: rail verdict + confidence + every evidence signal, and (if reconciled) the covered transactions and paise balance.

## Acceptance
- Steps 1–4 pass with no keys, deterministically.
- Per-hard-case metrics reported (never a single blended accuracy).
- Conservation invariants PASS.
- `--no-ai` report is byte-identical across runs.

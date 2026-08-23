# untangle — 5-minute demo script

The video the judges watch. Grounded in the real, reproducible output. Times are targets.
Record the terminal + the dashboard; speak plainly, no hype. Every number below is real.

---

## 0:00–0:30 — The problem, in money

> "This is one Indian merchant's bank account for a month. ₹4.5 crore came in — but not
> all from Razorpay. It's mixed with a second gateway, direct UPI, courier COD payouts,
> even personal transfers. Razorpay's own report reconciles the Razorpay *transactions* —
> but only *after* you know which of these bank credits are even Razorpay's. Nobody solves
> that first step. So this merchant's accountant does it by hand, and quietly loses the GST
> they could reclaim on the processing fee."

**On screen:** the dashboard hero — the account ribbon (the commingled bar) and the four figures.

## 0:30–1:30 — One command, real numbers

> "untangle reads three files — the bank statement, Razorpay's settlement report, the order
> ledger — and sorts every credit to its rail. One command, no AI, fully reproducible."

```bash
python -m engine.cli run --bank data/bank_statement.csv --recon data/recon_report.json \
  --ledger data/order_ledger.csv --out out/ --no-ai --seed 42
```

> "106 credits attributed to Razorpay — **zero** false positives. ₹2.97 crore reconciled to
> the paise. And **₹43,201 of recoverable fee-GST** surfaced — that's input tax credit the
> merchant was silently leaving on the table, and every rupee is traceable to a transaction."

**On screen:** the console output, then the dashboard figures.

## 1:30–2:45 — The honest part: it says "I don't know"

> "It didn't force-match everything. 26 credits it couldn't prove, it flagged — each with a
> reason and a next step. It abstains rather than guess, because a wrong 'this is Razorpay's'
> corrupts the books. Let me trace one."

```bash
python -m engine.cli why <line_key> --out out/
```

> "This credit matched a Razorpay settlement UTR exactly — tier A — and reconciled across 125
> transactions with a 7-paise rounding residual. Balanced. Fully explainable."

**On screen:** the exception queue, then the `why` trace.

## 2:45–3:45 — Break it on camera

> "The interesting question is where it *fails*. Every attribution is measured against a blind
> answer key, per hard case."

```bash
python -m eval.harness --run out/report.json --truth data/ground_truth.json
```

> "Precision 1.000 on every rail. Zero decoy false-positives — and those decoys are credits
> engineered to look like Razorpay; a naive keyword search gets 100% of them wrong, we get
> zero. On the genuinely hard cases — split settlements, destroyed UTRs — recall drops to
> 0.5–0.8, and you can see it *abstains* there rather than misattribute. I validated on four
> unseen seeds: precision and zero-decoy-FP hold; recall drops honestly to 0.86–0.94. Those
> are out-of-sample numbers, not a memorised benchmark."

**On screen:** the per-hard-case table; the difficulty-probe table showing naive baselines collapse.

## 3:45–4:30 — Where I used AI, and where I didn't

> "This is an AI builder track, so the honest answer matters. The matching, the arithmetic,
> the money verdict — all deterministic and unit-tested. AI is only allowed to read ambiguous
> narration text, and even then a deterministic rule confirms it. I benchmarked four models
> on that task — but I measured that on this data the AI adds ~zero marginal recall, because
> the deterministic core already catches what's catchable. So the shipped default is AI-off.
> The judgment was to measure it and *not* rely on it."

**On screen:** `docs/llm-benchmark.md` table.

## 4:30–5:00 — What broke, and the bar

> "Two independent audits caught real issues — a coincidental-amount misattribution path and
> a reconciliation ordering bug. I fixed both; the ordering fix actually *improved* coverage.
> Every schema claim in the repo cites a Razorpay fixture I verified myself, after getting
> burned by a confident wrong reading early — that's incident 001 in the repo. It's read-only
> toward money, PII is masked before any model call, and every decision is in a hash-chained
> audit log. 37 tests, deterministic, one command to reproduce every number on this screen."

**Close on:** the dashboard, and the repo's commit history.

---

## Shot list / prep
- Terminal with a readable font; `out/` pre-cleared so the run is live.
- Dashboard open in a browser (`python -m ui.dashboard` then serve `ui/`).
- Have a reconciled `line_key` and an exception `line_key` copied ready for the `why` shots.
- Rehearse the "why a set-sum, not a wider tolerance?" answer in case it's asked live (see
  [EXPLAINED.md](EXPLAINED.md)).
- Keep it calm and specific. The restraint *is* the pitch.

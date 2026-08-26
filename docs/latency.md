# Latency & scale

Measured on a 2020s laptop (Apple Silicon), deterministic path (`--no-ai`), seed 42.
Wall-clock via `/usr/bin/time -p`, so each figure **includes ~0.2 s Python interpreter
startup** — the steady-state engine cost is lower. Reproduce with the commands below.

| Workload | Bank credits | Settlement rows reconciled | p50 wall-clock | p95 wall-clock |
|---|---|---|---|---|
| Default sample | 294 | ~2.9k | **0.44 s** | 0.46 s |
| Scale ×34 stress | 294 | **413,319** | **11.67 s** | 11.69 s |

LLM cost is **$0** on both rows — the shipped default is `--no-ai`, so there are no token
charges and nothing leaves the machine. The AI tier, when explicitly enabled, adds one
masked call per residual UNKNOWN line only (see [llm-benchmark.md](llm-benchmark.md)).

## What actually scales here

The hard dimension is not the number of bank credits (a month is a few hundred) — it is
the **settlement/ledger volume** each credit must be reconciled against. The ×34 run pushes
that to 413k settled rows and still finishes in under 12 s, single-threaded, no database.
Attribution is O(bank credits); reconciliation is dominated by the settlement index build,
which is linear in settled rows. Both are pure-Python, stdlib-only, no external service.

## Reproduce

```bash
# steady-state, default sample — 5 runs
for i in 1 2 3 4 5; do
  /usr/bin/time -p .venv/bin/python -m engine.cli run \
    --bank data/bank_statement.csv --recon data/recon_report.json \
    --ledger data/order_ledger.csv --out out/ --no-ai --seed 42 >/dev/null
done

# 413k-settled-row stress dataset, then time it
.venv/bin/python -m generator.generate --seed 42 --scale 34 --out data_large
/usr/bin/time -p .venv/bin/python -m engine.cli run \
  --bank data_large/bank_statement.csv --recon data_large/recon_report.json \
  --ledger data_large/order_ledger.csv --out out_large/ --no-ai --seed 42 >/dev/null
```

Numbers will vary with hardware; the shape (sub-second at merchant scale, ~12 s at 400k
settled rows, $0 either way) is the claim.

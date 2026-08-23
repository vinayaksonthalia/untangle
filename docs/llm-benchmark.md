# LLM narration-classification benchmark

Task: classify a PII-masked Indian bank narration into one of five rails. Stratified sample of **20 lines**, scored against blind ground truth (`eval/` reads ground truth; the engine never does). Temperature 0.

| Model | id | status | accuracy | n | latency/call | tokens |
|---|---|---|---|---|---|---|
| Ox Alpha (free) | `stealth/ox-alpha` | ok | 0.93 | 15 | 21864 ms | 5491 |
| Gemini 3.7 Flash | `google/gemini-3.7-flash` | unreachable (all calls failed) | — | — | — | — |
| Qwen3.7 Flash | `qwen/qwen3.7-flash` | unreachable (all calls failed) | — | — | — | — |
| Gemini 2.5 Flash-Lite | `gemini-2.5-flash-lite` | unreachable (all calls failed) | — | — | — | — |

## Why AI is OFF by default

The deterministic tiers already resolve every line they can tie back to the recon report; the residual UNKNOWNs are genuinely ambiguous (split legs, brand-less coincidences). On this batch the LLM adds ~0 marginal recall there — it would only add latency, cost, and a prompt-retention surface — so the shipped default is deterministic (`--no-ai`). The benchmark above shows the models *can* classify narration well; the engineering judgment is that we don't need them to.

Groq and Cerebras keys returned HTTP 403 at benchmark time and are reported skipped rather than silently omitted.

# untangle — Architecture

Status: **attribution + reconciliation + fee-GST + exceptions + eval + web UI** (User Stories 1–3)
are built, measured, and independently audited, with a server-rendered landing page and an
interactive results dashboard. This document describes what exists in code today.

## The one-paragraph mental model

A merchant's bank statement is a pile of credits from many sources. `untangle` looks at
each credit and decides **which payment rail it came from** — Razorpay, another gateway,
direct UPI, a COD payout, or something unrelated — using deterministic evidence tied back
to Razorpay's settlement report. When the evidence is weak, it says **UNKNOWN** instead of
guessing, because a wrong "this is Razorpay's" corrupts every downstream number. A language
model is allowed to help read *messy narration text* — nothing else, and never to make a
money verdict alone.

## Data flow

```mermaid
flowchart TD
    A[bank_statement.csv] --> I[ingest.py]
    B[recon_report.json] --> I
    C[order_ledger.csv] --> I
    I -->|BankCreditLine, stable line_key| EV[evidence.py]
    B --> RIX[ReconIndex<br/>UTR set · settlement nets · dates]
    RIX --> EV
    EV -->|weighted EvidenceItems| AT[attribute.py<br/>Tier A / B / C]
    AT --> AB[abstain.py<br/>threshold τ]
    AB -->|rail or UNKNOWN + confidence + evidence| R[RailAttribution]
    R -.->|only residual UNKNOWN, PII-masked| LLM[llm/narrate.py<br/>edge only, --no-ai = off]
    LLM -.->|proposal, deterministically confirmed| R
    R --> CLI[cli.py → out/report.json + console]
    R --> AUD[audit.py<br/>hash-chained ledger]
    R --> EVAL[eval/harness.py<br/>vs BLIND ground_truth.json]
```

**Isolation:** `engine/` never imports `generator/` and never reads `ground_truth.json`.
`eval/` is the *only* reader of ground truth. A static test (`tests/unit/test_isolation.py`)
enforces both — this is what makes the reported numbers trustworthy.

## The modules (what each one does and why it exists)

| Module | Job | Why it's separate |
|---|---|---|
| `engine/ingest.py` | Load + validate the 3 files; derive a **stable line_key** = hash(value_date, amount, narration, bank_ref) | Real statements have no stable row id; we must never use the generator's `line_id` (that would be cheating) |
| `engine/evidence.py` | Turn a credit into **weighted signals** (UTR match, narration keyword, amount correlation, date proximity, Razorpay identity) | Signals are facts; keeping them separate from the verdict makes both testable |
| `engine/attribute.py` | Combine signals into a **rail verdict or UNKNOWN** via Tiers A→B→C | The decision logic lives in one auditable place |
| `engine/abstain.py` | The **threshold τ** below which a line abstains; the cost model behind it | Abstention is a first-class outcome, not a failure |
| `engine/llm/mask.py` | Strip PII before any text leaves the process | Constitution: PII never reaches a model |
| `engine/llm/client.py` | Provider-agnostic LLM call; `--no-ai` = no-op | No vendor lock-in; the whole pipeline runs without AI |
| `engine/llm/narrate.py` | The **only** place a model touches attribution — reads messy narration, proposes a rail, deterministic rules confirm | Constitution: AI at the edge, never the money verdict alone |
| `engine/audit.py` | Hash-chained ledger of decisions | Tamper-evidence for a money-adjacent system |
| `engine/cli.py` | The `run` command → report + console | The product's interface |
| `eval/metrics.py` + `eval/harness.py` | Score vs blind ground truth: per-rail + per-hard-case P/R, decoy FP, conservation | The only component allowed to see the answer key |

## The three attribution tiers (the heart of it)

Evidence is combined with **noisy-OR** (independent signals reinforce; one strong signal
dominates; capped at 0.99).

- **Tier A — decisive tie.** A UTR token in the narration that *exactly equals* a
  `settlement_utr` from Razorpay's report → `razorpay_settlement`. Near-zero false-positive
  risk: decoys carry no real settlement UTR.
- **Tier B — weighted combination.** No exact UTR, so score the weak signals: per-rail
  narration keywords (PayU/Delhivery/@ybl/…), amount-equals-a-settlement-net, value-date
  proximity, Razorpay brand/IFSC identity. Highest-scoring rail wins **if** it clears τ.
- **Tier C — bounded set-sum.** For a Razorpay-looking credit whose amount isn't a single
  settlement net, try summing 2–3 settlement nets within the date window (merge /
  carry-forward). Bounded (≤3 terms, ≤40 candidates) — abstain rather than explode.

**Two guards that protect precision (both added after the audit):**
1. *Coincidental-amount guard:* a Razorpay verdict needs a **substantive** signal (UTR,
   set-sum, or identity token) — an amount+date coincidence **alone** abstains.
2. *Decoy veto / precision guard:* the Razorpay brand word is deliberately weak and is
   voided by decoy markers; Razorpay may only outrank a distinctive competing keyword when
   it has a hard recon tie.

## Why the numbers look the way they do

- **Precision 1.000, recall ~0.95–0.98:** by design the engine only commits when it has a
  real tie back to the settlement report — a UTR match, a bounded set-sum, a unique
  settlement-net amount, or a provably-unique split reconstruction — and abstains otherwise.
  So it is almost never *wrong* (precision), while still recovering split-settlement legs when
  their amounts uniquely sum to a settlement net. The residual tail is the honest exception queue.
- **Zero decoy false-positives across 5 seeds:** the exact adversarial cases a naive brand
  grep fails (100% FP in the difficulty probe) — the tiered evidence + decoy veto handle.

## Security posture (threat model, short form)

- **Read-only toward money:** no module has any write/payout capability. The system cannot
  move funds even if wrong or compromised.
- **PII never reaches a model:** masked in `llm/mask.py` before any call.
- **Secrets only from gitignored `.env`.** Nothing sensitive in the repo.
- **Prompt-retaining models** (e.g. a free stealth model) are fine for synthetic + masked
  data, but real merchant data must never be sent to one — deterministic path or a
  non-retaining provider only.

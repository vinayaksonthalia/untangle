# Phase 0 Research — Multi-Rail Credit Attribution

Format per decision: Decision / Rationale / Alternatives considered.

## R1 — Language & dependencies
- **Decision**: Python 3.12+, stdlib-first; add only `hypothesis` (property tests) and use the stdlib HTTP client for the LLM call.
- **Rationale**: Matches the existing generator and Python fluency and auditability (defensible under review); minimal deps = fewer supply-chain and reproducibility risks (constitution IV/V).
- **Alternatives**: pandas (deferred — not needed for ~300 bank lines + 12k rows; adds weight); a vendor LLM SDK (rejected — an OpenAI-compatible HTTP call keeps us provider-agnostic).

## R2 — Attribution as tiered evidence-combining, not a single key
- **Decision**: Tier A exact evidence (clean UTR ↔ `settlement_utr`; exact amount+date to a settlement net) → Tier B scored weak evidence (narration rail patterns + amount correlation + value-date proximity) → Tier C constraint/set-sum for splits/merges/carry-forward. Each credit → rail | UNKNOWN with confidence + evidence trail.
- **Rationale**: The difficulty probe proved no single key achieves high precision AND recall (brand grep 0% on brand-less + 100% FP on decoys; clean-UTR 52% recall; amount 0% on split/merge/carry + 81% FP on collisions). Only combined evidence survives.
- **Alternatives**: single-key heuristics (proven to fail); a trained classifier (rejected for v1 — no real labeled data, harder to defend, and deterministic rules are auditable per constitution II).

## R3 — Set-sum coverage for splits/merges/carry-forward
- **Decision**: Bounded subset-sum over candidate recon rows constrained by settlement_id/date window, not a global search; cap candidate-set size and fall back to UNKNOWN when ambiguous.
- **Rationale**: Real coverage is many-recon-rows→one-credit; unbounded subset-sum is NP-hard, so constrain by the settlement grouping that already exists in the recon report and abstain rather than guess on blow-ups.
- **Alternatives**: exhaustive subset-sum (intractable, and a wrong "proof" is worse than abstention); greedy amount matching (fails on collisions — probe showed this).

## R4 — Calibrated abstention via an explicit cost model
- **Decision**: Auto-attribute only when confidence ≥ threshold τ; τ derived from a stated cost ratio (a wrong auto-attribution corrupts downstream reconciliation and books ≫ the ~2-minute cost of a human reviewing an escalation). Report the precision/coverage curve; τ is the chosen operating point, justified, not asserted.
- **Rationale**: Constitution IV — precision is the headline; UNKNOWN is a first-class, cheaper outcome. A derived τ with a curve beats a magic "99%".
- **Alternatives**: fixed 0.5/0.9 thresholds (arbitrary, indefensible); no abstention (guarantees wrong auto-matches on the hard tail).

## R5 — LLM provider strategy (edge only)
- **Decision**: One provider-agnostic OpenAI-compatible client; provider+model+key from env (`LLM_PROVIDER`, `LLM_MODEL`, and the matching `*_API_KEY`). Candidates to benchmark on the narration task: OpenRouter `stealth/ox-alpha` (free), Gemini, Groq, Cerebras. Used ONLY on residual UNKNOWN narrations; PII masked first; `--no-ai` disables it; it proposes a rail, deterministic rules confirm before any verdict stands.
- **Rationale**: Constitution II (AI at edges) + no vendor lock-in; benchmarking models is itself "AI judgment" evidence. Reproducible batch metrics live on the deterministic path; the AI path is measured separately (ablation).
- **Alternatives**: hard-wire one model (lock-in, and can't show the ablation cleanly); LLM does the matching (rejected — hallucination in the money path).
- **Security note**: `stealth/ox-alpha` retains prompts — fine for synthetic + PII-masked data; a real merchant statement must not be sent to a retaining model (route to non-retaining or stay deterministic).

## R6 — Fee-GST is extraction, not computation
- **Decision**: Recoverable fee-GST = Σ of the recon report's OWN `tax` (tax-on-fee, already inside `fee`) for reconciled transactions; per-transaction traceable. No tax-eligibility logic, no rate assumptions.
- **Rationale**: Verified from fixtures that `tax` is the GST on the fee and sits inside `fee`. Using Razorpay's own numbers makes the rupee headline unattackable; inventing tax logic is a correctness landmine.
- **Alternatives**: compute GST from MDR × rate (rejected — wrong-tax-claim risk); assert ITC eligibility (out of scope; not our call to make).

## R7 — Tamper-evident audit ledger
- **Decision**: Append-only JSONL; each entry carries the hash of the previous (hash chain); the daily root hash is committed to git, so GitHub's server-side push timestamp anchors it (attacker-uncontrolled). Claim stated precisely as "append-only with a hash chain, daily root anchored to git push timestamps."
- **Rationale**: Honest, cheap, and defensible; avoids the overclaim of unqualified "tamper-evident."
- **Alternatives**: unanchored hash file (theater — an attacker rewrites the whole file); OpenTimestamps/Bitcoin anchoring (stronger but overkill for scope; note as a possible upgrade).

## R8 — Stable per-line key
- **Decision**: Derive each bank line's key as a hash of (value_date, amount, narration, bank_ref); real statements lack a stable id.
- **Rationale**: The generator's `line_id` must not be used as attribution signal (leakage); a content hash works on real statements too.
- **Alternatives**: rely on `line_id` (leakage vector + doesn't exist on real data).

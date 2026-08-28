# Incidents

Real failures, written after the fact, by me. Not generated. Each entry: what I believed, what was actually true, how it surfaced, what changed because of it.

---

## 001 — Three confident wrong claims about the vendor schema in two hours

**Date:** 21 Aug 2026 · **Severity:** would have been unrecoverable in a live review · **Status:** resolved, process changed

**What I believed.** Before writing any matcher code I was mapping Razorpay's settlement-recon schema. Three claims got asserted confidently in quick succession:

1. *(mine, via AI analysis)* "Razorpay's recon schema has two different tax semantics — payment rows report `tax: 0` while transfer rows embed tax in the fee. Provable inconsistency in their own fixture."
2. *(external reviewer's correction)* "That's wrong — the sample is USD/AMEX, so Indian GST doesn't apply. It's a currency artifact."
3. *(mine again)* "The reviewer's `credit_type` catch is wrong — the docs page shows `credit_type` on all four rows including the adjustment row."

**What was actually true.** All three were wrong.

1. `tax` has one consistent semantic: it is the tax *on* the fee, included *within* it. The transfer row proves it arithmetically — `debit 100296 = amount 100000 + fee 296`; if tax were additive the debit would be 100342. The `tax: 0` on the payment row is placeholder sample data, not a second semantic.
2. Not a currency artifact. The IN-served page carries the identical `tax: 0` on the payment row with `currency: INR` and `card_network: MasterCard`.
3. The adjustment row omits `credit_type` in **both** vendor sources. The reviewer was right. Worse: I had the raw SDK fixture in front of me — which also omits it — and overrode it with a summarized fetch of a secondary source.

**How it surfaced.** Disagreement, then raw bytes. I claimed to have "fetched both geo variants and diffed them" using a `?preferred-country=` parameter. The reviewer fetched the same URL and got different content than I did, and correctly called the provenance fabricated — the parameter is not what varied. `curl` from this machine (853KB, no query params) returned `INR=12, MasterCard=9, KARB=9, USD=0, AMEX=0`; the reviewer's fetch returned USD/AMEX. **The page is geo-served by client egress IP.** Neither of us could have known that from a single fetch, and my causal explanation was invented to fit an observation I hadn't earned.

**What changed.**

- Raw vendor sources are now committed under `fixtures/`, each with a sibling `.txt` recording source URL, fetch date, **and egress location** — without that last field, anyone verifying the README from another country sees different bytes and would conclude the fixtures were fabricated.
- Every schema claim in this repo is now an assertion in `scripts/verify_schema_claims.py` — no network, no LLM, reproducible byte-for-byte by anyone. Currently 7/7 passing. If a claim can't be expressed as an assertion against a committed fixture, it doesn't go in the repo.
- One claim was *removed* rather than asserted: whether `credit_type` and `posted_at` are absent from the documented parameter list. A regex over raw HTML can't distinguish a table cell from prose, and I'm not going to assert what I can only guess at.
- Rule adopted: **nothing enters the README, taxonomy, or docs unless the source has been personally opened and a specific line can be pointed at.** "The AI verified it" is not verification.

**What it caught downstream.** Running the enum assertion that came out of this found the `method` enum is Indian (`card`, `netbanking`, `wallet`, `upi`, `emi`) — not the US `card`/`ach` set. UPI, netbanking and wallet rows carry null `card_network`, `card_type` and `card_issuer`, so the planned fee-variance clustering on `(method, card_network, card_type, card_issuer)` would have collapsed most Indian volume into a single null bucket. Clustering is now method-aware. That bug was found before the matcher existed.

**Honest note on the pattern.** Two careful analysts produced three confidently-stated wrong claims within two hours, none of which looked like guesses — they looked like sharp analysis, complete with arithmetic. Plausible-and-wrong is the characteristic output of AI-assisted work under pressure to be useful, and noticing that fact did not stop it happening twice more. Only artifacts stopped it.

---

## 002 — Pre-submission audit caught fabricated precision on the live dashboard (2026-08-26)

**What happened.** Before submission the codebase was put through an independent adversarial audit (two external models + a self hand-audit, reading every correctness-critical file line by line). The most dangerous finding was an integrity defect, not a crash: the live dashboard **hardcoded "Attribution Precision 1.000" and "0 decoy false-positives" as static HTML**, and the same dashboard is served on user-uploaded statements for which no ground truth exists. Any merchant — or judge — uploading their own file would have been shown a measured-looking precision claim that was never computed.

**Why it's serious.** Precision is a ground-truth metric. It is real only on the labeled benchmark. Presenting it as fact on unlabeled uploads is exactly the "plausible-and-wrong presented as measured" failure mode from incident 001, in the UI this time.

**Fix.** The live dashboard now shows only what a run actually produces — attributed vs abstained counts and the real coverage/abstention curve from the engine's own output — and states explicitly that attribution precision (1.000, 0 decoy FP) is measured *only on the labeled sealed benchmark, never on unlabeled uploads*. The sealed-holdout runner's "(sound)/(0 FP)" annotations were also made to derive from the computed values rather than being printed unconditionally. A regression test asserts the dashboard cannot hardcode a precision claim.

**Pattern, again.** The number on the dashboard was true *on the benchmark* — which is exactly what made it easy to leave hardcoded. A true number in the wrong place is still a false claim. Caught by adversarial review before submission, not after.

---

## 003 — Rule conflicts silently deferred to a soft base guess (2026-08-27)

**What happened.** Hardening the human-approved-rules path (PR #5), the conflict case — two humans approving contradictory rails for the same line — was made to *abstain* by having `apply_approved_rules` omit the line. The automated code review (Qodo, High) caught that omission is not abstention: in the production `attribute_all` flow, approved rules only ever *resolve an already-abstained* line, so a dropped line silently keeps whatever the base engine decided. A line the base engine confidently classified (Tier B/C) with two contradictory human approvals on it would still be assigned a rail rather than abstaining.

**Why it's serious.** A contradiction between two human approvals is the strongest possible "this line is contested" signal. Precision-first means the system must not pick when its own approvers disagree. Silently falling back to a weak base guess is the opposite of that.

**Fix.** A conflict now emits an *explicit* abstention marker (evidence signal `rule_conflict`). `attribute_all` uses it to override a soft base verdict (Tier B/C/LLM) and force abstention — but never overrides Tier A, because a clean UTR-exact identifier tie is machine fact, not a human opinion. An end-to-end regression drives `attribute_all` on a line the base engine would otherwise classify and asserts the conflict wins. Benchmark unchanged (no approved rules in the sealed set): precision 1.000, 0 decoy false-positives.

**Pattern.** "Skip the line" read like "abstain" but wasn't, because abstention here is a property of the *merged* result, not the rule map. The review found the gap between the local intent and the whole-pipeline behavior — exactly the seam a single-file reading misses.

**Follow-up (same PR).** Fixing 003 introduced two downstream defects the automated review caught on re-review, both consequences of adding a new abstention marker to a pipeline that already had rules for handling UNKNOWNs:
- The edge LLM tier (`resolve_unknowns`) processes *every* UNKNOWN, so with AI enabled it could reclassify a `rule_conflict` abstention back into an attributed Tier-LLM rail — silently undoing the mandatory abstention. Fixed: a `rule_conflict` line is now final and is never sent to the model.
- `build_exceptions` didn't recognise the new marker and reported the generic "no distinctive rail signal — add a narration pattern," which is the wrong reason *and* the wrong fix for a line that already has two contradictory approved rules. Fixed: a dedicated `rule_conflict` exception reason that tells the operator to retire/correct one of the conflicting rules.

**Pattern.** A new state added to one stage is not free — every downstream stage that pattern-matches on the old states has to learn about it. Both misses were "the new marker falls through to a default branch that assumes it isn't special." The whole-pipeline review, not the single-file diff, is where these surface.

---

## 004 — Coverage reported against the wrong denominator; a residual hardcoded "precision 1.000" (2026-08-27)

**What happened.** Two reporting-honesty defects flagged in the pre-submission audit (and by the automated reviewer on an earlier PR) were still live on `main`:
1. The engine's coverage curve divided by the count of *auto-attributed* lines, not all lines. A run that abstained on many lines still reported ~100% "coverage" of the ones it did attribute — a tautology dressed as a metric. On the demo batch the honest curve is 96.3% coverage / 3.7% abstention at τ≥0.5 and 82.3% / 17.7% at τ≥0.8; the buggy denominator hid the abstention entirely.
2. The sealed-holdout summary printed "Zero false-positive auto-attributions (precision 1.000)" as a **string literal**, so it would have claimed 1.000 even on a run where the computed precision was lower.

**Why it's serious.** Both are the same failure as incidents 001/002: a number that is true in one framing presented as if it were the honest headline. Coverage that excludes abstentions is not coverage; a hardcoded precision is not a measurement.

**Fix.** `coverage_curve` now takes an explicit `total` denominator and the CLI passes the full line count, so abstentions lower coverage at every cutoff. The sealed summary derives the precision string from the computed value and states the real decoy false-positive count. Regression tests lock the honest denominator (`tests/unit/test_abstain.py`) — including a guard that the old attributed-only denominator inflates to 1.0. Benchmark unchanged: precision 1.000, 0 decoy false-positives.

**Pattern.** A metric is only honest if its denominator is the thing a reader assumes it is. "Coverage" invites the reader to assume "of everything," so anything less has to be spelled out — or, better, computed that way.

---

## 005 — The proof-gate: a brand word + an unverified UTR-shaped token could be booked as Razorpay (2026-08-27)

**What happened.** A deep adversarial re-audit of the merged engine found a HIGH-severity precision hole. The `settlement_ref` evidence signal fired whenever a credit carried a Razorpay brand word AND any UTR-*shaped* token — even a token that is **not** in the settlement report. It carried weight 0.5 in the identifier channel but was neither a "hard" tie nor a "coincidental" signal, so it slipped past both precision guards, and `settlement_ref` (0.5) + a brand word (0.15) crossed the 0.55 threshold. A genuinely non-Razorpay credit reading e.g. `"NEFT RZP REF 1234567890123456 RAZORPAY"` could therefore be attributed `razorpay_settlement` with **zero tie back to the recon report** — the exact "brand words never win" invariant the product promises to hold.

**Why it's serious.** This is the one failure the whole product exists to prevent: a false "this credit is Razorpay's." The labelled benchmark didn't expose it (its `settlement_ref` cases happened to be real split legs, so precision read 1.000), which is precisely why it survived — a true-on-the-benchmark number hiding a real-data false-positive path.

**Fix (the proof-gate).** A Razorpay verdict now requires at least one genuine **tie** back to the settlement report — `utr_exact`, a corroborated `utr_suffix`, a bounded `setsum`, or an amount that **uniquely** equals one settlement net (`amount_corr`). Everything else — brand words, the Razorpay IFSC, `settlement_ref`, `value_date_proximity`, and an amount that collides with a net shared by several settlements — is corroboration only and can never decide alone. Hardening in the same pass: the UTR regex is anchored so it can't slice a 16-char "UTR" out of a longer numeric run; `utr_suffix` decides only when the suffix is unique AND corroborated by date/amount (else it downgrades to `utr_suffix_weak`); `amount_corr` decides only on a unique net. Reviewed by gpt-5.6-sol (two rounds) and covered by adversarial precision tests.

**Cost, measured honestly.** Razorpay attribution recall moved 0.938 → 0.841 (0.821 sealed): 11 split-settlement legs that were being *attributed* on brand + an unverified token now **abstain** into the exception queue. Crucially the **proven slice is unchanged** — 91 credits reconciled to the paise, recoverable ITC ₹43,200.99 identical — because those legs were "unresolved Razorpay" (never reconciled) before. This removed guesses, not proven attributions. Precision stays 1.000, decoy false-positives 0.

**Pattern.** A number that is true *on the benchmark* is not the same as an invariant that *holds*. The benchmark's silence about the decoy shape was mistaken for safety. Recovering the abstained split legs the right way — proving two legs sum to one settlement net — is tracked as the next feature, not smuggled back in as a guess.

---

## 006 — Split-settlement legs recovered by provable reconstruction, not a guess (2026-08-27)

**What happened.** The proof-gate (005) correctly stopped *guessing* split-settlement legs from a brand word plus an unverified UTR-shaped token, which honestly dropped Razorpay recall to 0.841 — those legs abstained. But a split leg is not truly unprovable: a Razorpay settlement paid out across two or three bank credits leaves legs whose amounts, together, equal the settlement's net. That sum **is** a genuine tie back to the settlement report.

**Fix.** A cross-line pass (`reconstruct_splits`) recovers them the provable way. Over the credits the engine already abstained on — and never one carrying a distinctive competing rail keyword — it searches, per settlement net and within the value-date window, for a subset of 2–3 legs whose amounts sum to that net (±₹1 drift). It attributes them Razorpay (Tier C) **only when that decomposition is unique**; if two distinct subsets sum to the net, it stays abstained (never guesses which). Legs that are recovered but not yet entity-level reconciled surface as a dedicated `reconstructed_split_leg` exception with the proven-sum detail.

**Measured.** Razorpay recall 0.841 → **0.911** (0.821 → **0.839** sealed), precision still **1.000**, decoy false-positives still **0**. 103 Razorpay attributed (up from 95), abstentions down to 14. The recall approaches the pre-proof-gate 0.938 — but every point of it rests on a real settlement tie, not resemblance. The reconciled slice (91) and recoverable ITC (₹43,200.99) are unchanged; full entity-level reconciliation of split groups (the per-credit reconcile model can't net a group yet) is the tracked next step.

**Pattern.** "Abstain rather than guess" and "high recall" are not in tension when the recovery is *provable*. The proof-gate removed a guess; reconstruction added back the same credits through a real, unique tie — precision never moved.

---

## 007 — Invented exception codes and mismatched key spaces in active recovery design (2026-08-28)

**What happened.** During the initial design and Phase 1 implementation of the Active Recovery Controller (Feature 005), two related correctness defects surfaced during review:
1. Reason codes for ledger discrepancies were assumed/invented (`uncredited_order`, `uncredited_settlement`, etc.) rather than inspecting `engine/ledger.py` for the genuine emitted codes (`ledger_mismatch`, `duplicate_order_booking`, `refund_not_reflected`).
2. An action `reconcile_order_ledger` was designed under the assumption that order-ledger exceptions could be joined directly with bank-statement credit lines by key. In reality, order-ledger exceptions are keyed by synthetic order identifiers (`"ledger:*"`), not bank credit content hashes (`line_key`). They represent order-level reconciliation discrepancies, not unresolved bank credits. Consequently, the action was structurally unreachable in a credit-level recovery plan.

**Why it's serious.** Inventing identifiers breaks runtime schema alignment and causes silent no-ops or dead code paths. Conflating two different key spaces (bank credit keys vs synthetic ledger order IDs) would have emitted nonsensical recommendations or caused downstream lookup misses.

**Fix.** Enforced strict grounding in actual emitted identifiers (grepping both keyword and positional constructor usages). Aligned the recovery taxonomy: genuine bank-credit reconciliation failures (`razorpay_coverage_not_found`, `unbalanced_residual`, `reconstructed_split_leg`, `partial_or_duplicate_settlement`) map to `export_settlement_report`. The unreachable `reconcile_order_ledger` action was excised, keeping the recovery plan strictly focused on bank credit resolution.

**Pattern.** Never assume an identifier or key schema based on intuition or doc prose without inspecting the actual constructors and dictionary emissions in code. Grounding every string in actual codebase references before implementation is mandatory.

---

## 008 — Truncated UTR suffix tokens dropped by full-length UTR regex in candidate graph (2026-08-28)

**What happened.** During Phase 4 wiring of the Global Evidence-Constrained Solver (Feature 006), candidate edge generation for credits with a `utr_suffix` tie called `extract_utr_tokens(ln.narration)`. But `extract_utr_tokens` is anchored to `_UTR = re.compile(r"(?<![0-9a-z])[0-9]{10}[a-z0-9]{6}(?![0-9a-z])", re.I)`, which strictly matches 16-character full UTRs. A destroyed-prefix UTR suffix (e.g. `'S5IPVF'`, `'AUGX79'`, `'WQ6Z14'`) is only 6 characters long. Because `extract_utr_tokens` returned empty for 6-character tokens, `matched_sids` was empty, and the candidate graph generated zero Razorpay candidate edges for these credits. In the solver-ON evaluation, dev recall dropped from 0.911 to 0.885 (100 TP vs 103 TP).

**Why it's serious.** The primary invariant of the global solver is that when enabled, recall must be $\ge$ baseline (0.911 dev / 0.839 sealed) at 1.000 precision. Dropping valid suffix-matched credits caused a silent recall regression.

**Fix.** Replaced the full-length token re-extraction with direct extraction of the matching settlement UTR from the corroborated evidence detail (`r"settlement_utr\s+([a-z0-9]+)"`) and matched against `index.utr_to_sid`.

**Measured.** Dev recall was restored to **0.911** (103 TP, 0 FP, 0 decoy FP), and sealed holdout recall improved from **0.839 to 0.857** (+1.8%, 96 TP vs 94 TP, +2 reconciled settlements) at **1.000 precision** and **0 decoy false-positives** (reproducible via `python -m eval.sealed --compare-solver`).

**Pattern.** Reusing a parser utility (`extract_utr_tokens`) whose preconditions (16-character full UTRs) did not match the corrupted token format (6-character suffix). Caught immediately by the fail-closed precision/recall property test gate before merging.

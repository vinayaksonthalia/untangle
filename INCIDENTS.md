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

# Untangle Constitution

Untangle is a multi-rail bank-credit attribution engine for Indian merchants, built
as a Razorpay AI Buildathon submission. This constitution governs every spec, plan,
task, and line of code. It supersedes convenience.

## Core Principles

### I. Honesty & Measurement (NON-NEGOTIABLE)
No cherry-picked results, ever — "one match proves nothing." Every reported metric is
computed against blind, immutable ground truth the engine never sees at build time.
Every factual/schema claim in the repo cites a committed source line, verifiable by
`scripts/verify_schema_claims.py`. Failures, abstentions, and limitations are reported,
never hidden. A number we cannot reproduce does not ship.

### II. Deterministic Core, AI Only at the Edges (NON-NEGOTIABLE)
Every decision that touches money, attribution, or arithmetic is deterministic, rule-
based, and unit-tested. An LLM is used ONLY for genuinely ambiguous free-text
(bank-narration entity resolution) — never for math, never for a final money verdict.
The system MUST run and be graded with AI fully disabled; a no-AI ablation quantifies
the model's exact marginal value. If AI adds two points, we report two points.

### III. Test-First & Property-Based (NON-NEGOTIABLE)
Conservation invariants (no rupee vanishes; matched + exceptions = credit; no double-
attribution; idempotent re-runs) are encoded as property-based tests and must pass
before dependent work proceeds. The data generator and the matcher live in isolated
contexts: the matcher never imports or reads generator source — only its frozen output
and the published taxonomy. This isolation is enforced and documented.

### IV. Security & Least Privilege (NON-NEGOTIABLE)
The engine is read-only toward money: it requests zero write/payout scopes and is
structurally incapable of moving funds. Customer PII is masked before any LLM call.
Secrets live only in a gitignored `.env` and are never committed. The audit log is
append-only and tamper-evident. When uncertain, the engine ABSTAINS (UNKNOWN) rather
than assert a wrong attribution — a false "this is Razorpay's" is worse than an escalation.

### V. Professional Craft on Every Surface
Code, tests, documentation, UI, and developer experience are all held to a production
bar — none is an afterthought. Clone-and-run in one command. Every error is handled and
human-readable; every empty/loading/failure state is designed. The UI is polished and
accessible. Strategy/planning documents never enter the product repository.

## Security Requirements

- Documented threat model: what the system can and cannot do, and why, architecturally.
- No network calls to any money-moving endpoint; test-mode / read-only APIs only.
- Input validation on every ingested file (statement, recon report, ledger).
- Deterministic, seeded, reproducible builds — byte-identical outputs for identical inputs.
- Dependency hygiene: stdlib-first; every third-party dependency justified.

## Development Workflow & Quality Gates

- Strict Spec-Driven Development: constitution → specify → plan → tasks → implement →
  converge. No implementation without an approved spec and plan.
- Every build phase's output gets an independent Opus review/audit BEFORE the next phase
  builds on it. Specialized review lenses per surface: correctness, security, UI/UX, tests.
- Daily commits; honest, iterative git history (they read it).
- Nothing is pushed to the remote without a review of the exact push contents. The repo
  stays private until submission, then flips public.
- Real failures during the build are logged in `INCIDENTS.md` by the human, after the fact.

## Governance

This constitution supersedes all other practices. Amendments are versioned and dated
here. Any complexity must be justified against these principles. The claim-verification
rule (cite the line or cut the claim) is binding on humans and agents alike. All work —
specs, plans, tasks, reviews — must verify compliance with these principles.

**Version**: 1.0.0 | **Ratified**: 2026-08-23 | **Last Amended**: 2026-08-23

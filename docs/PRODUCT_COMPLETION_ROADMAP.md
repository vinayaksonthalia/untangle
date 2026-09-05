# Untangle Product Completion Roadmap

## Purpose

This document is the durable source of truth for completing Untangle after PR #71. Work proceeds
phase by phase. Antigravity may implement the work, but each phase must be independently verified
against the current repository rather than assuming this roadmap or an earlier audit is correct.

The objective is a secure, multi-tenant, precision-first finance-controller product. Deterministic
code owns monetary calculations, attribution, reconciliation, journals, recovery decisions, and
certificates. Language-model output remains advisory.

## Working protocol

For every phase, Antigravity must:

1. Begin from the latest `main` and read `AGENTS.md`, `README.md`, `SECURITY.md`, the relevant
   architecture documents, production code, tests, migrations, and CI configuration.
2. Inspect the actual code paths and prove each claimed gap. Treat previous reviews as hypotheses.
3. Research authoritative sources when security, standards, provider formats, or third-party APIs
   are involved. Record sources and the decisions they support.
4. Ask the user for guidance only when a required product choice, credential, authentic fixture,
   external account, or irreversible migration cannot be safely inferred.
5. Keep scope limited to the current phase. Do not redesign unrelated UI, perform broad refactors,
   or implement later phases early.
6. Add executable tests that fail before the change and pass afterward, including denial, failure,
   abstention, cross-tenant, and replay paths where applicable.
7. Run focused tests while developing and all repository verification gates before handoff.
8. Update relevant documentation and clearly state migrations, deployment changes, limitations,
   and any work blocked by unavailable authentic evidence or external infrastructure.
9. Commit the completed phase, push one focused branch, open one PR, and stop. Do not merge it and
   do not begin the next phase.
10. End with a summary of files and behavior changed, tests and exact results, commit SHA, branch,
    PR link, migrations, deployment steps, remaining limitations, and questions requiring review.

The user may request prompts for later phases before earlier PRs are reviewed. Each implementer must
still base its work on the latest `main`; it must not stack a new phase on an unmerged PR unless the
user explicitly requests a dependent stacked PR.

## Non-negotiable guardrails

- Use integer paise for money and preserve deterministic ordering, canonical serialization,
  provenance, replay identity, and explicit abstention.
- Never allow an LLM to establish evidence, change money, override abstention, approve a journal,
  execute recovery, or issue a certificate.
- Never claim native provider support without authentic sanitized evidence or authoritative
  documentation.
- Never commit credentials, signing keys, private financial data, raw statements, generated inputs,
  or `out/` artifacts.
- Enforce authorization on the server and at the data-access boundary. UI visibility is not access
  control.
- No ordinary engineer access to customer data. Any future exceptional access must be least
  privilege, time-limited, explicit, and audited.
- Never silently truncate, guess, recompute, downgrade signing, retry an uncertain money-affecting
  request, or turn an unsupported input into a financial conclusion.
- Do not call a demo, mock, in-memory scaffold, file export, or untested connector production-ready.

## Phase 0 — Repository truth and claim correction

Inventory every product, API, MCP, evaluation, and UI capability and trace it to production code,
tests, documentation, and evidence. Verify the reported limitations against current HEAD. Correct
misleading claims about synthetic benchmarks, generic Razorpay schemas, provider support, unsigned
certificates, proposal-only recovery, and file-export integrations. Publish a capability matrix with
`verified`, `limited`, `demo-only`, `evaluation-only`, `planned`, and `unsupported` states.

**PR:** claims, labels, capability inventory, and documentation only; no functional expansion.

## Phase 1 — Persistent data architecture and tenant isolation

- Design a PostgreSQL-compatible relational model for users, organisations, memberships, roles,
  uploads, runs, reports, investigations, certificates, approvals, and immutable audit events.
- Add versioned migrations and documented upgrade/rollback/startup behavior.
- Introduce storage repositories/services without coupling deterministic finance code to the web or
  database framework.
- Give every private record an immutable organisation owner and use non-enumerable public IDs.
- Require tenant scope in every query, route, service, download, background-job payload, and cache
  key; use database-level isolation controls where the chosen stack supports them.
- Add executable cross-tenant and IDOR tests for reads, lists, downloads, updates, deletes, and
  guessed identifiers.
- Define retention/deletion semantics and separate shared, labelled sample data from private data.
- Do not create fake authentication in this phase. Establish a testable trusted principal boundary
  that Phase 2 can connect to real authentication.

**PR:** persistent tenant-scoped foundation. It must not store private uploads through an unscoped
path and must not be presented as a complete account system.

## Phase 2 — Authentication, organisations, and permissions

Implement a secure identity/session architecture, organisation creation/invitations, membership,
logout/revocation/expiration, CSRF protection, secure cookies, and server-enforced roles: owner or
admin, operator or preparer, reviewer or approver, and read-only auditor. Define and test the
permission matrix for uploads, runs, reports, investigations, recovery proposals, approvals,
exports, certificates, integrations, and organisation administration. Audit security-relevant
actions and test privilege escalation and cross-tenant access. Do not build homemade cryptography or
treat hidden buttons as authorization.

**PR:** complete authenticated organisation boundary and permission enforcement.

## Phase 3 — Saved runs and multi-month workspace

Persist source identities, immutable canonical results, provenance, engine/rule/adapter versions,
status, exact totals, abstentions, and replay identity. Add saved-run listing, filtering, reopening,
pagination, multi-month grouping and exact comparisons. Support replay with pinned historical
configuration versus latest configuration as two clearly distinct new outputs. Never silently
recompute or mutate a historical/certified run. Add retention and deletion behavior.

**PR:** persistent run history and genuine multi-month operating workspace.

## Phase 4 — Private file storage and secure processing

Add an encrypted private object-storage abstraction for temporary uploads, retained sources,
canonical results, exports, and certificates. Use organisation-scoped keys, authenticated streaming
or short-lived authorized URLs, explicit retention, and interrupted-upload recovery. Validate size,
MIME and file signatures, extensions, archive expansion, row counts, schemas, contradictory money,
and spreadsheet formula risks. Browser storage becomes a convenience cache, not authoritative data.

**PR:** private storage and safe upload lifecycle; no public objects or raw financial logs.

## Phase 5 — Background jobs, large files, and hosted reliability

Move long processing out of synchronous HTTP requests into durable jobs. Persist progress and state,
add idempotency and cancellation, and bound concurrency, memory, rows, archive expansion, solver work,
and time. Store large results server-side with pagination and downloadable canonical artifacts.
Replace unexplained 503/504 behavior with actionable states. Add health checks, privacy-safe metrics,
stress tests, and concurrency tests. Never return partial conclusions or silently truncate.

**PR:** reliable asynchronous processing and large-result access.

## Phase 6 — Private MCP and the Untany agent interface

Classify current MCP tools as public demo, trusted local, authenticated private, or unsupported.
Implement authenticated, tenant- and permission-bound MCP access to start runs, check status, query
saved evidence, list abstentions, inspect verification, and draft advisory summaries. Add optional
Untany conversational UX over those tools. Every answer must cite retrieved run evidence or admit
that it is unavailable. Test prompt injection and cross-tenant leakage. Never send unnecessary raw
records to a model or let a model create financial truth or approvals.

**PR:** permission-aware private MCP and advisory agent, plus accurate setup/tool/limitation docs.

## Phase 7 — Certificate issuer identity and key management

Extend PR #71's fail-closed Ed25519 work with organisation-bound issuer identity, key IDs, signing
policy, secure key storage, activation, rotation, revocation, and historical verification. Bind
decision-affecting issuer information into the canonical signed body. Clearly distinguish unsigned
integrity, valid signatures, trusted issuers, unknown issuers, and revoked keys. Test tampering,
wrong tenant/key, rotation, revocation, and canonicalization. Never store plaintext private keys or
rewrite historical certificates.

**PR:** issuer-authenticated organisation certificates and documented production key operations.

## Phase 8 — Evidence-backed provider-format ingestion

Create a conservative, versioned provider-adapter acceptance process. Add named Razorpay, HDFC,
ICICI, SBI, Axis, or PDF formats only when backed by authentic sanitized fixtures with permission or
authoritative format documentation. Preserve row provenance, exact money, structural markers, and
actionable unsupported-format errors. Test malformed and adversarial variants. Bind adapter identity
into reports and certificates. If evidence is unavailable, deliver only the framework and mark named
support blocked; do not invent compatibility from synthetic narration.

**PR:** verified adapters and exact provider-support matrix, limited by available authentic evidence.

## Phase 9 — Controlled accounting integrations

Preserve and validate Tally XML export. Add a secure integration abstraction, connection management,
preview, role-based approval, optional separation of duties, immutable payload hash, idempotency,
external references, delivery state, dry-run/sandbox mode, and result reconciliation. Implement Tally
or Zoho posting only against official documentation and a usable test environment. Treat timeouts
after submission as uncertain state and never retry blindly. An LLM cannot approve or post.

**PR:** approval-controlled integration foundation and only those connectors that are actually
verified.

## Phase 10 — Recovery workflow and controlled execution

Add immutable, evidence-bound recovery cases with proposed, reviewing, approved, rejected, exported,
submitted, externally confirmed, failed, and cancelled states. Require permissions, optional dual
approval, versioning after changes, policy limits, expiry, external references, and duplicate/replay
protection. Keep recommendation separate from execution. Never execute from ambiguous/abstained
evidence, autonomously move money, or let model output trigger approval.

**PR:** production-grade recovery case management; external execution remains connector-specific and
gated.

## Phase 11 — Security, privacy, and operational hardening

Threat-model tenants, uploads, storage, jobs, MCP, LLMs, signing keys, connectors, and administration.
Test IDOR, CSRF, session fixation, escalation, malicious uploads, archive bombs, formula injection,
prompt injection, cache leakage, replay, SSRF, uncertain submissions, and secret leakage. Add backup
and restore tests, migration/rollback validation, audit-log integrity, privacy export/deletion,
retention controls, incident response, key-compromise procedures, dependency scanning, and clean
deployment verification. Do not claim regulatory certification from internal tests.

**PR:** hardening, operational runbooks, and deploy verification.

## Phase 12 — Final product truth, documentation, and release audit

Refresh the capability matrix and document the user, admin, integration, MCP/agent, security,
provider-support, certificate, deployment, and limitation models. Verify that every advertised
feature is functional and reachable, and every unsupported feature is absent or labelled planned.
Exercise the complete organisation-to-certificate workflow, run all repository gates, and publish a
release summary with exact migrations, deployment steps, implemented capabilities, and remaining
limitations. Synthetic examples must remain labelled; never claim universal support or that AI made
deterministic financial decisions.

**PR:** documentation and release readiness only after the preceding foundations are merged.

## Mapping of the 15 known limitations

| Limitation | Planned treatment |
| --- | --- |
| Tab-private temporary results | Phases 3–5 add private persistence; tab storage becomes optional cache. |
| No saved history | Phase 3. |
| No authentication/organisations | Phases 1–2. |
| Public MCP is demo-oriented | Phase 6 preserves demo scope and adds authenticated private MCP. |
| Razorpay JSON is Untangle's schema | Phases 0 and 8 correct claims and add only evidenced adapters. |
| Integrity is not issuer identity | Phase 7. |
| Browser size limits | Phases 4–5 use server-side storage, pagination, and downloads. |
| Hosted concurrency/timeouts | Phase 5. |
| No direct Tally/Zoho integration | Phase 9, only with official evidence/test access. |
| No production recovery execution | Phases 9–10 add human-controlled workflow, never autonomous action. |
| Synthetic benchmarks | Phase 0 labels them; Phase 12 re-audits claims. |
| Limited provider-format evidence | Phase 8. |
| No persistent multi-month workspace | Phase 3. |
| LLM narration is advisory | This remains a permanent safety boundary, strengthened in Phase 6. |
| No universal settlement coverage | This remains an honest limitation; Phases 0, 8, and PR #71 improve and document bounded coverage and abstention. |

## Planned PR sequence

1. PR A — Capability audit and honest claims
2. PR B — Persistence and tenant-scoped data model
3. PR C — Authentication, organisations, and permissions
4. PR D — Saved history and multi-month workspace
5. PR E — Private file storage and background processing
6. PR F — Private MCP and Untany
7. PR G — Organisation-bound certificate identity
8. PR H — Evidence-backed provider adapters
9. PR I — Accounting integrations and approvals
10. PR J — Recovery workflow
11. PR K — Security and operational hardening
12. PR L — Final documentation and release audit


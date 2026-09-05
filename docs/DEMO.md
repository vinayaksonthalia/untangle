# untangle — Comprehensive Demo Script & Submission Video Guide

This script guides the official submission video for judges and evaluators. It demonstrates both Untangle's **instant public demo** and the **enterprise multi-tenant platform**.

Scope note: Paytm and Cashfree entries in the demo dataset are synthetic,
narration-based examples only. They are not native Paytm or Cashfree statement
format integrations, and this demo makes no provider-format support claim.

---

## Act 1 — The Problem & Instant Public Demo (0:00–1:45)

### 0:00–0:30 — The Problem, in Money
> *"This is an Indian merchant's bank account for a month. ₹4.5 crore arrived, commingled across Razorpay, Paytm, Cashfree, Direct UPI, and courier COD payouts. Razorpay's settlement report reconciles transactions, but only after you know which bank credits actually belong to Razorpay. Accountants do this by hand, guessing on matching amounts and silently leaking input tax credit on processing fees."*

- **Visual**: The Untangle landing page (`/`) and dashboard ribbon showing the commingled bank stream.

### 0:30–1:15 — Instant Sample Run (`/try-sample`)
> *"Untangle solves this without requiring cloud infrastructure or database setups for trial. Click 'Try Sample Dataset'. In under two seconds, Untangle ingests the bank statement, settlement report, and order ledger in memory."*

- **Action**: Click `/try-sample`. The browser sessionStorage hydrates instantly.
- **Visual**: The four headline metrics:
  - **₹2.97 crore** reconciled to the exact integer paise.
  - **103 credits** attributed to Razorpay with zero false positives.
  - **₹43,201 of recoverable fee-GST** surfaced for immediate tax credit claim.
  - **Zero guesswork**: 26 ambiguous credits flagged for human review.

### 1:15–1:45 — The Cryptographic Period Close Certificate
> *"Untangle issues an independent, verifiable certificate. Notice the SHA-256 digest binding the exact bank statement, ledger, and engine rules. Anyone can verify this certificate independently without access to our database."*

- **Visual**: The Certificate View, demonstrating hash verification and the Tally XML export button.

---

## Act 2 — Hosted Enterprise Architecture & Worker Pipeline (1:45–3:30)

### 1:45–2:30 — Asynchronous Reconciliation & Worker Fencing
> *"In production enterprise mode, reconciliation runs on a hardened multi-tenant architecture. Let's submit a full monthly reconciliation through the authenticated API."*

- **Terminal / API Call**:
  ```bash
  curl -X POST http://localhost:8080/api/tenant/reconcile \
    -H "Cookie: untangle_session=$TOKEN" \
    -H "X-Untangle-CSRF: 1" \
    -H "Idempotency-Key: demo-run-may-2026" \
    -H "X-Period-Start: 2026-05-01" \
    -H "X-Period-End: 2026-05-31" \
    -F "bank=@data/bank_statement.csv" \
    -F "recon=@data/recon_report.json" \
    -F "ledger=@data/order_ledger.csv"
  ```
- **Explanation**:
  > *"The HTTP request returns immediately with 202 Accepted. The upload is staged to private S3 object storage, and a reconciliation job is registered in PostgreSQL under strict Row-Level Security."*

- **Worker in Terminal**:
  ```bash
  python -m persistence.worker --once
  ```
  > *"Our background worker claims the job using a PostgreSQL atomic lease. Notice the stages: input validation, engine execution, S3 artifact promotion, and a single-transaction state transition. If a worker crashes, attempt fencing and heartbeat expirations prevent duplicate work or corruption."*

### 2:30–3:00 — Multi-Month Period Comparison
> *"Accounting is about trends and drift. Untangle allows one-click comparison between consecutive accounting periods."*

- **API Call**:
  ```bash
  curl -X POST http://localhost:8080/api/tenant/runs/compare \
    -H "Cookie: untangle_session=$TOKEN" \
    -H "X-Untangle-CSRF: 1" \
    -H "Content-Type: application/json" \
    -d '{"run_a_id": "run_01J_APR", "run_b_id": "run_01J_MAY"}'
  ```
- **Visual**: The comparison JSON showing:
  - Exact integer paise deltas across months.
  - Rail volume drift (e.g. UPI share increasing vs card settlements).
  - Root-cause migration (fee drifts resolved vs new exceptions).

### 3:00–3:30 — Untany: The Advisory Agent with Hard Boundaries
> *"Untangle includes Untany, an AI advisor for financial controllers. But notice our strict boundary: AI never touches the ledger, never changes numbers, and never posts money."*

- **Test 1: Factual Inquiry**:
  - Prompt: *"What is the total reconciled amount and unresolved balance?"*
  - Untany response: Returns ₹2,97,00,000.00 reconciled with full evidence breakdown and mandatory advisory disclaimer.
- **Test 2: Mutating Intent Refusal**:
  - Prompt: *"Please approve the journal entry and transfer the money."*
  - Untany response: **REFUSED**.
  > *"Untangle is a read-only finance controller. The agent service cannot move money, approve journals, certify closes, or override reconciliation decisions."*

---

## Act 3 — Security, Compliance & Verification (3:30–5:00)

### 3:30–4:15 — Legal Hold & Audit Defense
> *"When tax authorities conduct an audit, records must be immutable. Let's place an active legal hold on this reconciliation run."*

- **Action**: Call `POST /api/tenant/runs/{id}/legal-hold`.
- **Attempt Deletion**: Call `DELETE /api/tenant/runs/{id}`.
- **Result**: `409 Conflict` — blocked by the repository and database check constraints. Audit event recorded in the immutable audit log.

### 4:15–4:45 — Fail-Closed Health Probes & Backup Restoration
> *"We don't do silent demo fallbacks in production. In enterprise mode, `/readyz` fails closed if the database or migration is degraded. And we provide automated restoration verification."*

- **Terminal**:
  ```bash
  python scripts/verify_restore.py
  ```
  > *"This script restores a backup into an isolated database, validates all 20 tables, checks the migration head, confirms foreign keys and column schemas, and tests tenant isolation."*

### 4:45–5:00 — Final Wrap-Up
> *"Untangle proves that AI in finance doesn't mean trusting an LLM with money. It means deterministic precision, integer paise arithmetic, cryptographic verifiability, and conversational advisement that knows when to say no."*

---

## Recording Checklist & Environment Setup

1. **Pre-requisites**:
   - Python virtualenv activated (`.venv/bin/activate`).
   - Clean test database: `sqlite:///tests/web/web_test.db` or PostgreSQL.
   - S3 storage configured or MinIO running locally.
2. **Terminal Windows**:
   - Window 1: Web server (`uvicorn webapp.app:create_app --factory --port 8080`).
   - Window 2: Worker daemon (`python -m persistence.worker`).
   - Window 3: Curl requests and evaluation runner.
3. **Browser**:
   - Tab 1: `http://localhost:8080` (Landing & Demo).
   - Tab 2: `http://localhost:8080/app` (Upload & Reconcile).
   - Tab 3: `http://localhost:8080/docs` (Swagger OpenAPI UI).

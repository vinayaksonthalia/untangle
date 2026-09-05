# Untangle Frontend Engineering & UI Handoff Specification

This specification defines the complete HTTP and WebSocket/SSE integration contract between the Untangle backend services and the frontend client application.

---

## 1. Architectural Operating Modes

Untangle supports two distinct deployment and operational modes:

| Mode | Entry Point | State Storage | Multi-Tenancy | Worker Model |
|---|---|---|---|---|
| **Public Demo Mode** | `/app`, `/try-sample`, `/reconcile` | Ephemeral `sessionStorage` in browser tab | None (single guest context) | In-process bounded thread pool |
| **Enterprise Tenant Mode** | `/api/tenant/*`, `/api/auth/*` | PostgreSQL with Row-Level Security (RLS) & S3 Object Storage | Strict multi-tenant isolation by `organisation_id` | Distributed asynchronous worker (`untangle_worker`) |

The frontend client should check server readiness and authentication state on initialization.

---

## 2. Authentication & Session Security

### 2.1 Cookie & Transport Policy
- **Session Cookie**: `untangle_session`
  - Flags: `HttpOnly; Secure; SameSite=Strict; Path=/`
  - Issued upon successful OIDC exchange (`/api/auth/oidc/callback`).
  - Contains high-entropy opaque token; backend validates against cryptographic hash stored in `user_sessions`.
- **CSRF Protection Header**:
  - All mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) across `/api/tenant/*` **MUST** include:
    ```http
    X-Untangle-CSRF: 1
    ```
  - Requests omitting this header receive `403 Forbidden` (`{"detail": "Missing CSRF protection header"}`).

### 2.2 Roles and Permission Hierarchy
- `owner`: Full control over organisation, memberships, runs, legal holds, data purge.
- `admin`: Reconciliation execution, viewing runs/artifacts, placing/releasing legal holds.
- `member`: Read-only access to completed runs, certificates, and presentation analytics.

---

## 3. Health & Readiness Probes

The frontend monitoring and load balancers rely on fail-closed probes:

- `GET /livez`:
  - Returns `200 OK` (`{"status": "live"}`) if FastAPI process is operational.
- `GET /readyz`:
  - Validates PostgreSQL connectivity, Alembic schema version, and database write capability.
  - In private hosted mode, fails closed with `503 Service Unavailable` if database is unconfigured or degraded.
- `GET /healthz`:
  - Public demo endpoint returning version, git commit, and system status.

---

## 4. Reconciliation Job Submission & Async Lifecycle

Because reconciliation across hundreds of thousands of transactions involves multi-file hashing, attribution, and artifact generation, all tenant reconciliations are asynchronous.

### 4.1 Initiate Reconciliation
```http
POST /api/tenant/reconcile
Content-Type: multipart/form-data
X-Untangle-CSRF: 1
Idempotency-Key: <unique-uuid-v4>
X-Period-Start: 2026-04-01
X-Period-End: 2026-04-30

FormData:
  bank: [bank_statement.csv]
  recon: [recon_report.json]
  ledger: [order_ledger.csv]
```

#### Headers:
- `Idempotency-Key` *(Required)*: Client-supplied unique token (UUIDv4). Identical payload replays return cached `202 Accepted`. Payload mismatches with same key return `409 Conflict`.
- `X-Period-Start` *(Optional, YYYY-MM-DD)*: Start date of accounting period.
- `X-Period-End` *(Optional, YYYY-MM-DD)*: End date of accounting period (must be `>= X-Period-Start`).

#### Response: `202 Accepted`
```json
{
  "job_id": "job_01J...",
  "run_id": "run_01J...",
  "status": "queued",
  "stage": "queued",
  "message": "Reconciliation job accepted and queued for worker processing."
}
```

### 4.2 Job Polling Protocol
```http
GET /api/tenant/jobs/{job_id}
```

#### Status Lifecycle:
- `queued`: Awaiting idle worker claim.
- `running`: Worker has claimed job lease; stages transition predictably:
  1. `validating_inputs`: Checking file hashes, formats, and byte limits.
  2. `reconciling`: Engine executing deterministic attribution and fee calculation.
  3. `storing_artifacts`: Uploading immutable reports, certificates, and Tally XML to S3.
  4. `finalizing`: Atomic PostgreSQL transaction committing results and closing run.
- `completed`: Processing succeeded; results and artifacts are ready.
- `failed`: Terminal failure (`error_code`, `error_summary`).
- `cancelled`: Cooperatively aborted by user request.

#### Polling Guidance:
- Poll every 2.0 seconds while status is `queued` or `running`.
- When status reaches `completed`, navigate user to `/tenant/runs/{run_id}`.

### 4.3 Cancel Queued or Running Job
```http
POST /api/tenant/jobs/{job_id}/cancel
X-Untangle-CSRF: 1
```
#### Response: `200 OK`
```json
{
  "job_id": "job_01J...",
  "status": "cancelled",
  "message": "Job cancellation requested successfully."
}
```

---

## 5. Runs & Presentation API

### 5.1 List Runs (Cursor-Paginated)
```http
GET /api/tenant/runs?cursor=<opaque_cursor>&limit=20
```

#### Response: `200 OK`
```json
{
  "items": [
    {
      "public_id": "run_01J...",
      "status": "completed",
      "reporting_period_start": "2026-04-01",
      "reporting_period_end": "2026-04-30",
      "legal_hold": false,
      "engine_version": "1.0.0",
      "reconciliation_hash": "a1b2c3...",
      "created_at": "2026-04-30T18:00:00Z"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0Ijog...",
  "has_more": true
}
```
*Note: Cursors use stable non-null `(created_at, id)` keys to prevent skipped items during concurrent ingestion.*

### 5.2 Get Run Presentation Data
```http
GET /api/tenant/runs/{run_id}/presentation
```
Returns structured presentation metrics formatted for the UI dashboard:
- `summary`:
  - `total_credit_paise`: Total inbound bank credit in integer paise.
  - `reconciled_paise`: Reconciled amount in integer paise.
  - `unresolved_paise`: Unmatched balance in integer paise.
  - `fee_gst_recoverable_paise`: Recoverable input tax credit in integer paise.
- `rails`: Array of payment rail distributions (`razorpay_settlement`, `direct_upi`, etc.).

### 5.3 Get Investigations & Exceptions
```http
GET /api/tenant/runs/{run_id}/investigations
```
Returns array of root-cause investigations:
```json
[
  {
    "line_key": "bl_01...",
    "root_cause": "mdr_fee_drift",
    "resolved": true,
    "variance_paise": 1250,
    "confidence": 0.95
  }
]
```

### 5.4 Get Verified Certificate
```http
GET /api/tenant/runs/{run_id}/certificate
```
Returns cryptographic period close certificate:
```json
{
  "public_id": "cert_01...",
  "is_signed": true,
  "content_sha256": "...",
  "report_sha256": "...",
  "certificate_json": { ... }
}
```

### 5.5 Download Immutable S3 Artifacts
```http
GET /api/tenant/runs/{run_id}/artifacts/{artifact_type}
```
Streams raw artifact directly from private object storage (`S3` or `LocalStorageBackend`).

#### Supported `artifact_type` values:
- `bank_statement`: Original uploaded CSV.
- `recon_report`: Original uploaded JSON.
- `order_ledger`: Original uploaded CSV.
- `presentation_json`: Presentation metrics.
- `report_json`: Full deterministic audit trail.
- `certificate_json`: Verifiable closing certificate.
- `journal_tally_xml`: XML journal voucher for direct accounting software ingestion.

---

## 6. Multi-Month Run Comparison

Enables merchants and auditors to compare accounting periods (e.g. April 2026 vs May 2026) to detect drift, volume variances, and fee changes.

```http
POST /api/tenant/runs/compare
Content-Type: application/json
X-Untangle-CSRF: 1

{
  "run_a_id": "run_01J_APRIL",
  "run_b_id": "run_01J_MAY"
}
```

### Response: `200 OK`
```json
{
  "run_a": { "run_id": "run_01J_APRIL", "period_start": "2026-04-01", "period_end": "2026-04-30" },
  "run_b": { "run_id": "run_01J_MAY", "period_start": "2026-05-01", "period_end": "2026-05-31" },
  "deltas": {
    "total_credit_paise": 5000000,
    "reconciled_paise": 4800000,
    "unresolved_paise": 200000,
    "fee_gst_recoverable_paise": 15000
  },
  "rails_comparison": [
    { "rail": "razorpay_settlement", "delta_paise": 4000000, "delta_count": 40 }
  ],
  "root_cause_drift": {
    "mdr_fee_drift": { "count_a": 12, "count_b": 18, "delta_count": 6 }
  }
}
```

### Validation Constraints:
- Both runs must belong to the active tenant.
- Both runs must be in `completed` status (otherwise `409 Conflict`).
- Reporting periods must be distinct and non-overlapping (otherwise `422 Unprocessable Entity`).

---

## 7. Untany Advisory Agent Service

The advisory agent provides natural language explanations over closed reconciliation runs.

```http
POST /api/tenant/agent/query
Content-Type: application/json
X-Untangle-CSRF: 1

{
  "run_id": "run_01J...",
  "query": "What is the total reconciled amount and recoverable fee GST?"
}
```

### Strict Architectural Boundaries:
- **Refusal on Mutating Intent**: The agent refuses all requests to approve journals, modify ledgers, move money, or certify closes (`status: "refused"`).
- **Factual Determinism**: Resolves queries purely against the immutable `AgentEvidenceSnapshot`.
- **Explicit Abstention**: Abstains on ambiguous or out-of-domain queries (`status: "abstained"`).
- **Advisory Notice**: Every response includes the mandatory compliance disclaimer:
  *"Untangle AI agent responses are advisory only. Calculations, attributions, journals, and certificates are deterministic and verifiable in the canonical report."*

---

## 8. Compliance & Legal Hold

Merchants undergoing statutory tax audits can place runs under legal hold to prevent deletion or purging.

### 8.1 Toggle Legal Hold
```http
POST /api/tenant/runs/{run_id}/legal-hold
Content-Type: application/json
X-Untangle-CSRF: 1

{
  "legal_hold": true,
  "reason": "Statutory GST assessment FY 2026-27"
}
```
*Permissions: Requires `owner` or `admin` role.*

### 8.2 Soft-Delete Run
```http
DELETE /api/tenant/runs/{run_id}
X-Untangle-CSRF: 1
```
- If `legal_hold == true`, the operation is blocked: `409 Conflict` (`{"detail": "Run is under legal hold and cannot be deleted"}`).
- If allowed, sets `is_deleted = true`, records audit event `"run.deleted"`, and moves artifacts to tombstone retention.

---

## 9. Error Format & Common HTTP Status Codes

All errors conform to FastAPI standard JSON schema:
```json
{
  "detail": "Human-readable explanation of error."
}
```

| HTTP Code | Meaning | Example Scenario |
|---|---|---|
| `400 Bad Request` | Malformed input or illegal transition | Attempting to cancel an already completed job |
| `401 Unauthorized` | Missing or invalid session cookie | Unauthenticated request to `/api/tenant/*` |
| `403 Forbidden` | Role permission failure or missing CSRF | Member attempting to place a legal hold |
| `404 Not Found` | Entity not found in active tenant scope | Requesting a run belonging to another organisation |
| `409 Conflict` | Mutex collision or legal hold violation | Deleting a run under active legal hold; idempotency payload collision |
| `422 Unprocessable Entity` | Field or period validation failure | `X-Period-End` precedes `X-Period-Start` |
| `503 Service Unavailable` | Storage or DB unavailable | Hosted mode fail-closed health check failure |

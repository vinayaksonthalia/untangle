# Persistence Architecture and Strict Tenant Isolation (Phase 1)

Status: **Implemented and independently verifiable.** This document describes the PostgreSQL persistence foundation, strict dual-layer tenant isolation, schema constraints, migration management, and retention design established in Phase 1 of Untangle's product-completion roadmap.

---

## 1. Verified Previous Storage Behavior

Prior to Phase 1, Untangle operated as a stateless, in-memory proof of concept:
- **No Database**: No relational database, ORM, SQLite file, or migration system existed in the repository.
- **In-Memory Uploads**: User uploads (`/reconcile` and `/api/reconcile`) were buffered into memory snapshots (`reconcile_bytes`), reconciled synchronously by worker threads, and discarded upon request termination.
- **Browser-Tab Storage**: Reconciliation results were serialized and returned to the client browser inside an HTML bootstrap payload that stored the bundle in `sessionStorage` (`untangle_results`). Server endpoints `/api/presentation/current`, `/api/investigations/current`, and `/api/certificate/current` returned HTTP 410 Gone; client-side JavaScript (`webapp/static/run-session.js`) intercepted dashboard navigation and read from tab storage.
- **Zero Ownership**: Domain models (`BankCreditLine`, `ReconRow`, `RunReport`, `AuditLedger`) contained no concept of tenant, organisation, or principal ownership.
- **Process-Global Singletons**: Static sample and evaluation fixtures relied on process-global singleton caches (`_DEMO_CACHE`, `_SEALED_CACHE`, `_INVESTIGATIONS_CACHE`).

---

## 2. Persistence Architecture & Boundary

The persistence architecture resides under `persistence/`, strictly separated from the deterministic finance engine (`engine/`):

```text
┌────────────────────────────────────────────────────────┐
│             Web / Transport (FastAPI)                  │
│   Unauthenticated Public Demo    (Future) Auth (Ph 2)  │
└───────────────────────────┬────────────────────────────┘
                            │ TenantContext (Principal, Org, Role)
┌───────────────────────────▼────────────────────────────┐
│         Service Layer (UnitOfWork & Orchestration)      │
│   Three-phase transaction lifecycle & session binding  │
└─────────────┬────────────────────────────┬─────────────┘
              │ Pure In-Memory             │ Scoped Queries
┌─────────────▼────────────┐ ┌─────────────▼────────────┐
│   Deterministic Engine   │ │   Persistence Repositories│
│ (Paise exact, stdlib)    │ │ (Composite FKs + RLS)     │
└──────────────────────────┘ └─────────────┬────────────┘
                                           │ SQL + set_config
                             ┌─────────────▼────────────┐
                             │       PostgreSQL 16      │
                             │  Row-Level Security (RLS)│
                             │  Immutability Triggers   │
                             └──────────────────────────┘
```

The deterministic reconciliation engine (`engine/`) remains pure, stdlib-first, and completely decoupled from SQLAlchemy, PostgreSQL, ORMs, and web sessions.

---

## 3. Entity & Ownership Model

Every tenant entity carries an immutable `organisation_id` foreign key referencing `organisations(id)`.

Child entities referencing a reconciliation run (`uploaded_file_metadata`, `reconciliation_results`, `investigations`, `certificates`, `artifact_metadata`) enforce ownership integrity via **composite foreign keys**:
```sql
FOREIGN KEY (organisation_id, run_id) 
    REFERENCES reconciliation_runs(organisation_id, id) 
    ON DELETE RESTRICT
```
This relational constraint guarantees at the database engine level that an investigation, certificate, or result in Organisation A can never point to a reconciliation run belonging to Organisation B.

### Identifiers
- **Internal Surrogate Primary Keys**: `BigInteger` generated via database identity/autoincrement, used strictly for joins and foreign keys. Never exposed over public APIs.
- **Opaque Public Identifiers**: Non-enumerable, type-prefixed strings (`org_...`, `usr_...`, `run_...`, `cert_...`) carrying 128 bits of cryptographically secure random entropy (`secrets.token_hex(16)`). Insertion uses savepoint-nested retries trapping SQLSTATE `23505` to safely resolve rare collisions.

---

## 4. Tenant-Context & Control-Plane Bootstrap Flow

To resolve the RLS bootstrap chicken-and-egg problem without circular dependencies, tables are divided into two distinct zones:

1. **Control-Plane Tables**: `organisations`, `principals`, `roles`, `organisation_memberships`.
   - Access is governed by authenticated principal identity.
   - Queried by the control-plane repository to discover authorized organisations.
2. **Tenant Data-Plane Tables**: `reconciliation_runs`, `uploaded_file_metadata`, `reconciliation_results`, `investigations`, `certificates`, `artifact_metadata`, `audit_events`.
   - Protected by PostgreSQL Row-Level Security (RLS) and repository query scoping.

### Resolution Flow:
```text
1. Authenticated Principal Identity (Phase 2 token / test fixture)
2. Query active principal record
3. Query active organisation memberships for principal
4. Select active organisation & resolve verified Role ('owner', 'admin', 'operator', 'reviewer', 'auditor')
5. Issue immutable TenantContext(organisation_id, principal_id, role, request_id)
6. Open UnitOfWork: executes SELECT set_config('app.current_tenant_id', :org_id, true)
7. Execute tenant queries under active RLS protection
```

> [!IMPORTANT]
> **Tenant Context Security Posture**:
> The application-controlled `app.current_tenant_id` session setting is trusted input to PostgreSQL RLS. RLS acts as defence in depth against omitted query filters or developer error, but does not independently authenticate the user. Authentication of the principal and active membership verification occurs in the application control plane prior to issuing a `TenantContext`.

---

## 5. PostgreSQL Row-Level Security (RLS) Policy

RLS is enabled and enforced (`FORCE ROW LEVEL SECURITY`) on all tenant tables:
```sql
ALTER TABLE reconciliation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconciliation_runs FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON reconciliation_runs
    FOR ALL
    TO untangle_app
    USING (organisation_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
    WITH CHECK (organisation_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint);
```
- **Fail-Closed**: When `app.current_tenant_id` is unset or empty, `current_setting(..., true)` returns `NULL`, matching 0 rows for `SELECT`, `UPDATE`, and `DELETE`, and raising a policy violation on `INSERT`.
- **Transaction-Local**: The setting is configured via `SELECT set_config('app.current_tenant_id', :tid, true)` with `is_local=true`. Upon `COMMIT` or `ROLLBACK`, PostgreSQL automatically resets the parameter, preventing tenant state from leaking across pooled connections.

---

## 6. Three-Phase Transaction Lifecycle

Long-running deterministic reconciliation is decoupled from database transactions to prevent connection pool exhaustion and deadlocks:

1. **Phase 1: Ingestion & Initiation (DB Transaction 1)**:
   - Begin transaction with `set_config`.
   - Insert `reconciliation_runs` with `status = 'initiated'` and `started_at = NOW()`.
   - Insert `uploaded_file_metadata` with SHA-256 hashes and sizes.
   - Append `audit_events` (`event_type = 'run.initiated'`).
   - Commit.
2. **Phase 2: Engine Execution (Zero DB Locks Held)**:
   - Deterministic engine processes immutable memory snapshots (`reconcile_bytes`).
   - Computes canonical report text, hashes, certificate, and Tally XML.
3. **Phase 3A: Atomic Completion (DB Transaction 2)**:
   - Begin transaction with `set_config`.
   - Lock run row `FOR UPDATE`.
   - If already completed, returns existing run idempotently.
   - Atomically insert `reconciliation_results`, `investigations`, `certificates`, `artifact_metadata`.
   - Append `audit_events` (`event_type = 'run.completed'`).
   - Update `reconciliation_runs` to `status = 'completed'` and `completed_at = NOW()`.
   - Commit.
4. **Phase 3B: Atomic Failure Recording (DB Transaction 3)**:
   - On error during Phase 2 or 3, a clean transaction locks the run row `FOR UPDATE`.
   - If already completed, preserves completed state without overwriting.
   - Updates status to `failed`, `failed_at = NOW()`, with sanitized `error_code` and `error_summary`.
   - Appends `audit_events` (`event_type = 'run.failed'`).
   - Commit.

---

## 7. Database-Enforced Immutability

Application-level immutability is reinforced at the database engine level via PostgreSQL triggers:
```sql
CREATE OR REPLACE FUNCTION trg_prevent_record_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is immutable: UPDATE and DELETE operations are prohibited', TG_TABLE_NAME
        USING ERRCODE = 'P0001';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_events_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();

CREATE TRIGGER trg_certificates_immutable
BEFORE UPDATE OR DELETE ON certificates
FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();

CREATE TRIGGER trg_results_immutable
BEFORE UPDATE OR DELETE ON reconciliation_results
FOR EACH ROW EXECUTE FUNCTION trg_prevent_record_mutation();
```
SQLSTATE `P0001` (`raise_exception`) distinguishes immutability violations from unique constraints or foreign key violations. Direct SQL `UPDATE` or `DELETE` statements are rejected by the database.

---

## 8. Retention & Deletion Policy

> [!NOTE]
> Retention duration is organisation policy and legal-review dependent. Phase 1 preserves records until an explicit, configured retention policy is implemented.

- **No Blanket Cascading Deletion**: Child evidence records do not use `ON DELETE CASCADE` from organisations or runs.
- **Certificates, Results, and Audit Events**: Protected by foreign keys with `ON DELETE RESTRICT` and database triggers preventing updates and deletions.
- **Reconciliation Runs and Organisations**: Support soft-deletion (`is_deleted = TRUE`, `deleted_at = NOW()`). Queries exclude soft-deleted runs by default (`scoped_select`).

---

## 9. Migration Operations & Local Setup

### Environment Variables
- `DATABASE_URL`: Runtime connection string (e.g. `postgresql+psycopg://untangle_app:pass@localhost:5432/untangle`).
- `MIGRATION_DATABASE_URL`: Privileged DDL migration connection string (e.g. `postgresql+psycopg://untangle_migrator:pass@localhost:5432/untangle`).
- If `DATABASE_URL` is unset, Untangle operates in zero-database public demo mode.

### Commands
```bash
# Apply migrations to head
python -m persistence.migrate upgrade head

# Inspect current database revision
python -m persistence.migrate current

# Check if database matches expected head
python -m persistence.migrate check

# Downgrade by one revision (non-destructive migrations only)
python -m persistence.migrate downgrade -1
```

### Production Startup Behavior
When `DATABASE_URL` is set, application lifespan executes `persistence.migrate.verify_schema_current()`. If unmigrated, startup aborts immediately with an actionable error. Application startup never silently creates or mutates production schema.

---

## 10. Sample vs Private Data Separation

- Public sample endpoints (`/try-sample`, `/api/presentation/sample`, `/api/certificate/sample`, etc.) remain 100% database-independent, serving pre-computed synthetic benchmarks without touching the persistence layer.
- Private tenant records are never accessible through sample routes.
- Shared sample data is clearly labelled as synthetic.

---

## 11. Known Limitations & Phase 2 Integration Boundary

- **Authentication is Not Shipped in Phase 1**: Phase 1 establishes the database schema, repositories, and `TenantContext` boundary. User-facing login, registration, invitations, and session cookies belong to Phase 2.
- **No Private HTTP Routes in Phase 1**: Private persistence is validated through internal service and repository test suites; production private endpoints will be exposed in Phase 2 once authentication is active.
- **Raw Object Storage Belongs to Phase 4**: `uploaded_file_metadata` and `artifact_metadata` store file metadata, sizes, and SHA-256 checksums; encrypted cloud object storage for raw statement files is scheduled for Phase 4.
- **Background Job Execution Belongs to Phase 5**: Background workers (e.g. Celery / asynchronous queues) will be implemented in Phase 5.
- **LLM Narration Remains Advisory**: AI narration never establishes financial evidence or overrides deterministic verdicts.

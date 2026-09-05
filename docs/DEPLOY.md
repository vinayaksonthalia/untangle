# Deploying Untangle

Untangle is designed for dual deployment:
1. **Public Demo Mode**: Ephemeral in-memory processing. Zero database, zero external storage, zero credentials required.
2. **Enterprise Hosted Mode**: Fully isolated multi-tenant architecture with PostgreSQL Row-Level Security (RLS), S3/MinIO immutable object storage, asynchronous background workers, and fail-closed health probes.

---

## 1. Fast Path — Render Blueprint

The easiest way to deploy both the web application, background worker daemon, and managed PostgreSQL instance is via Render's infrastructure-as-code blueprint:

1. Push this repository to GitHub.
2. In Render dashboard: **New → Blueprint** → select your repository.
3. Render parses [`render.yaml`](../render.yaml) and provisions:
   - `untangle-web`: FastAPI application service with health check on `/readyz`.
   - `untangle-worker`: Background worker processing reconciliation jobs.
   - `untangle-postgres`: PostgreSQL 16 database with multi-tenant schema.
4. Set S3 environment variables (`UNTANGLE_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).

---

## 2. Docker & Container Deployment

### 2.1 Public Demo Mode (Single Container)
```bash
docker build -t untangle .
docker run -p 8080:8080 -e UNTANGLE_MODE=demo untangle
```
- Listens on `http://localhost:8080`.
- Supports `/try-sample`, `/app`, `/reconcile`, and public certificate verification.
- Ephemeral client-side session storage; no data persisted to host disk.

### 2.2 Enterprise Multi-Tenant Mode
When running in hosted mode, run separate containers for the web API and background worker:

#### Web Service:
```bash
docker run -d --name untangle-web -p 8080:8080 \
  -e UNTANGLE_MODE=hosted \
  -e DATABASE_URL="postgresql://untangle_app:pass@postgres:5432/untangle" \
  -e AUTH_DATABASE_URL="postgresql://untangle_auth:pass@postgres:5432/untangle" \
  -e UNTANGLE_STORAGE_BACKEND=s3 \
  -e UNTANGLE_S3_BUCKET="my-tenant-storage" \
  -e AWS_REGION="ap-south-1" \
  untangle uvicorn webapp.app:create_app --factory --host 0.0.0.0 --port 8080
```

#### Background Worker Service:
```bash
docker run -d --name untangle-worker \
  -e UNTANGLE_MODE=hosted \
  -e DATABASE_URL="postgresql://untangle_app:pass@postgres:5432/untangle" \
  -e WORKER_DATABASE_URL="postgresql://untangle_worker:pass@postgres:5432/untangle" \
  -e UNTANGLE_STORAGE_BACKEND=s3 \
  -e UNTANGLE_S3_BUCKET="my-tenant-storage" \
  -e AWS_REGION="ap-south-1" \
  untangle python -m persistence.worker
```

---

## 3. Database Role Provisioning & Migrations

For PostgreSQL deployments, provision the least-privilege roles prior to running migrations:

```bash
# Provision roles and RLS policies
psql -U postgres -d untangle -f scripts/provision_db_roles.sql

# Apply database migrations to head (0003_reconciliation_jobs_and_storage)
alembic upgrade head
```

### PostgreSQL Roles:
- `untangle_fn_owner`: Owner of `SECURITY DEFINER` claim, mutex, and session issuance functions.
- `untangle_app`: Application role bound to tenant RLS context (`app.current_tenant_id`).
- `untangle_worker`: Dedicated background worker role with atomic claiming privileges.
- `untangle_auth`: Isolated authentication role for OIDC session creation.

---

## 4. Health Probes & Monitoring

Untangle exposes three health endpoints:

| Endpoint | Probe Type | Behavior |
|---|---|---|
| `GET /livez` | Kubernetes Liveness | Returns `200 OK` (`{"status": "live"}`) if process is responding. |
| `GET /readyz` | Kubernetes Readiness | Validates database connectivity, migration status, and storage. In hosted mode, returns `503 Service Unavailable` if database is down or unconfigured. |
| `GET /healthz` | Public Status | Returns application version, commit hash, and engine status. |

---

## 5. Verifying Database Backup & Restoration

Untangle includes an automated script to verify database restoration integrity:

```bash
# Test restoration from an existing SQLite or PostgreSQL dump
python scripts/verify_restore.py --database-url "$DATABASE_URL"

# Or verify clean migration cycle in isolated temporary scratch DB
python scripts/verify_restore.py
```

The verification script checks:
- Presence of all 20 core relational schema tables.
- Alembic head migration (`0003_reconciliation_jobs_and_storage`).
- Metadata columns (legal hold, reporting periods, S3 storage keys).
- Foreign key integrity.
- Cross-tenant RLS query isolation.

---

## 6. Local Development Quickstart

```bash
# 1. Install dependencies
pip install -e ".[web]"

# 2. Start local web server
uvicorn webapp.app:create_app --factory --port 8080 --reload

# 3. Start local worker (in separate terminal)
python -m persistence.worker
```

# Deploy untangle

untangle is a single FastAPI app with **zero third-party runtime dependencies** beyond
`fastapi`/`uvicorn` (everything else is stdlib). Admitted uploads become bounded, immutable byte
snapshots; the app does not persist them to its filesystem or a database, and no secret is required.
Any container host works.

## Fastest path — Render (free tier)

1. Push this repo to GitHub (already done).
2. Render dashboard → **New → Blueprint** → select this repo.
3. Render reads [`render.yaml`](../render.yaml), builds the [`Dockerfile`](../Dockerfile), and gives you a
   live `https://untangle-*.onrender.com` URL. No env vars to set.

The health check hits `/` (the landing page). First request after an idle spin-down takes a few
seconds on the free tier — that is Render cold-start, not the app.

## Public demo safeguards

`/healthz` provides a non-sensitive readiness/version response. The app adds request IDs, latency-only
structured logs, security headers, per-file upload limits, and bounded JSON verification payloads.
Per-file limits are enforced while reading multipart parts; aggregate multipart size is enforced by
counting ASGI body bytes, including chunked or missing-`Content-Length` requests.
Reconciliation is limited to two worker slots and returns `503` when saturated; a wait beyond 90 seconds
returns `504`. A timed-out Python thread may finish in the background, so its slot remains occupied until
it returns and no cancellation is claimed.

Upload/API reconciliation and certificate verification use a small per-IP in-memory limit (20 requests
per minute). This is suitable for the single-instance demo only; multiple workers/replicas need shared
rate limiting and concurrency control. The MCP transport remains separately mounted with its protocol
and CORS behavior.

The hosted demo must run as a single instance with one worker: active runs are held in the process-local
`_RUNS` store. Shared multi-worker storage is out of scope for this demo. This is the same limitation as
the existing “single-instance demo only” deployment boundary above.

## Any Docker host (Fly.io, Cloud Run, a VM)

```bash
docker build -t untangle .
docker run -p 8080:8080 untangle        # -> http://localhost:8080
```

The image honours a platform-provided `$PORT` (Fly/Cloud Run set it), defaulting to `8080`.
It runs as an unprivileged user and ships no build tooling.

## Local, without Docker

```bash
pip install -e ".[web]"
uvicorn webapp.app:app --port 8080 --workers 1       # -> http://localhost:8080
```

## Routes

| Route | What it is |
|---|---|
| `/` | Landing page |
| `/app` | Upload the three files and reconcile |
| `/try-sample` | Run the seeded sample end-to-end (no upload needed) |
| `/api/docs` | OpenAPI docs |

`/try-sample` and `/reconcile` return `303 See Other` to `/dashboard` and set an active-run cookie; callers
that do not follow redirects must request the dashboard explicitly.

## Verification status

The `uvicorn` start command in the Dockerfile `CMD` is verified locally — `GET /` and `GET /app`
both return `200`. The Docker image build itself has **not** been run in this environment (no Docker
daemon available here); build it once on a machine with Docker before relying on it for the demo.

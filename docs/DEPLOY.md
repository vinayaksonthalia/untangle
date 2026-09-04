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

The hosted demo may run as a single instance with one worker for predictable resource limits. Private
results are held in the browser tab's `sessionStorage` bundle; the server retains no private result store.
During processing, the server necessarily sees uploaded bytes in memory (and may briefly spool multipart
uploads), then releases them. This is not a promise that engineers cannot access process memory.

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

`/try-sample` and `/reconcile` return a no-store bootstrap page that writes a bounded result bundle to
browser-tab `sessionStorage` and then navigates to `/dashboard`. Refreshes preserve the bundle; normal
tab close clears it, though browser session restore and duplicated tabs may retain or copy it. The UI's
Clear action removes it explicitly. Legacy `/api/*/current` endpoints return `410 Gone`.

The 4 MiB limit is a tab-storage threshold, not a reconciliation rejection: larger completed
bundles are returned as a no-store `untangle-results.json` download containing presentation,
investigations, certificate and Tally XML. If browser storage rejects a smaller bundle, the
completion page offers the same download. Large bundles are not loaded into the dashboard.
The printable certificate independently verifies its envelope and renders only fields from
that certificate, never editable presentation totals. Unsigned hashes do not authenticate an issuer.

This is a breaking browser-route migration from `303` plus a run cookie to `200` HTML plus
JavaScript navigation. Non-browser integrations should use `/api/reconcile` for report JSON;
requesting `/dashboard` alone does not populate results. Stored browser data is display data,
not evidence of authenticity: the Verify screen still checks certificates independently.

### Browser regression check

With a local server on port 8766 and Playwright available in your development environment:

```bash
node tests/browser/tab_results.cjs
```

This exercises separate browser profiles uploading distinct synthetic files, independent tabs,
refresh, certificate downloads, navigation, clearing, corrupt storage, and unavailable storage.
Generate the normal synthetic `data/` fixtures first; never use private statements for this check.
Set `UNTANGLE_TEST_URL` to test another local port. Playwright is test tooling, not a runtime dependency.

## Verification status

The `uvicorn` start command in the Dockerfile `CMD` is verified locally — `GET /` and `GET /app`
both return `200`. The Docker image build itself has **not** been run in this environment (no Docker
daemon available here); build it once on a machine with Docker before relying on it for the demo.

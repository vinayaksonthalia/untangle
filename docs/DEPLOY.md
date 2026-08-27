# Deploy untangle

untangle is a single FastAPI app with **zero third-party runtime dependencies** beyond
`fastapi`/`uvicorn` (everything else is stdlib). It processes uploads in memory and stores
nothing, so any container host works and no database or secret is required.

## Fastest path — Render (free tier)

1. Push this repo to GitHub (already done).
2. Render dashboard → **New → Blueprint** → select this repo.
3. Render reads [`render.yaml`](../render.yaml), builds the [`Dockerfile`](../Dockerfile), and gives you a
   live `https://untangle-*.onrender.com` URL. No env vars to set.

The health check hits `/` (the landing page). First request after an idle spin-down takes a few
seconds on the free tier — that is Render cold-start, not the app.

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
uvicorn webapp.app:app --port 8080       # -> http://localhost:8080
```

## Routes

| Route | What it is |
|---|---|
| `/` | Landing page |
| `/app` | Upload the three files and reconcile |
| `/try-sample` | Run the seeded sample end-to-end (no upload needed) |
| `/api/docs` | OpenAPI docs |

## Verification status

The `uvicorn` start command in the Dockerfile `CMD` is verified locally — `GET /` and `GET /app`
both return `200`. The Docker image build itself has **not** been run in this environment (no Docker
daemon available here); build it once on a machine with Docker before relying on it for the demo.

# untangle — production image. Runtime has zero third-party deps beyond the `web` extra
# (fastapi/uvicorn); everything else is stdlib. Small, deterministic, no build tooling shipped.
FROM python:3.12-slim

# No .pyc writes, unbuffered logs, deterministic hashing off by default for reproducibility.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install deps first (layer-cached) — copy only the packaging metadata, then the source.
COPY pyproject.toml README.md ./
COPY engine ./engine
COPY eval ./eval
COPY ui ./ui
COPY webapp ./webapp
COPY generator ./generator
COPY persistence ./persistence
COPY mcp_server.py ./

RUN pip install --upgrade pip && pip install -e ".[web,mcp]"

# Pre-generate & authenticate the sealed evaluation holdout artifact during build
RUN python -m eval.sealed

# Run as an unprivileged user; give it a writable home for the runtime sample dataset.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8080

# Honour the platform-provided $PORT (Render/Fly/Cloud Run set it); default 8080 locally.
# `exec` replaces the shell with uvicorn so it becomes PID 1 and receives SIGTERM directly —
# graceful shutdown on deploy/scale-down instead of running to the forced-kill timeout.
CMD ["sh", "-c", "exec uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]

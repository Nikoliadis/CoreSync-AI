# syntax=docker/dockerfile:1.7
# Build context is the repository root so that packages/ can be copied in later phases.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ---- dependency layer -------------------------------------------------------
# Cached independently of source, so a code change rebuilds in seconds.
FROM base AS deps
COPY apps/api/pyproject.toml apps/api/uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev 2>/dev/null \
    || uv sync --no-install-project --no-dev

# ---- development ------------------------------------------------------------
FROM deps AS development
RUN uv sync --no-install-project
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
COPY apps/api/ .
EXPOSE 8000
CMD ["uvicorn", "coresync.presentation.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- production -------------------------------------------------------------
FROM base AS production
RUN groupadd -r app && useradd -r -g app -u 10001 -d /app app
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
COPY --chown=app:app apps/api/src ./src
COPY --chown=app:app apps/api/migrations ./migrations
COPY --chown=app:app apps/api/alembic.ini ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1
CMD ["gunicorn", "coresync.presentation.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000", \
     "--timeout", "60", "--graceful-timeout", "30", \
     "--max-requests", "10000", "--max-requests-jitter", "1000", \
     "--access-logfile", "-"]

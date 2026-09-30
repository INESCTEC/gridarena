# syntax=docker/dockerfile:1

# Containerizes the gridarena/GridArena FastAPI app. This does not replace the
# local `uvicorn gridarena.app:app --reload` workflow described in the README —
# it just packages the same app so it can also be run as a container.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# build-essential: compiles any dependency without a prebuilt wheel for this
# platform. libgomp1: OpenMP runtime required at import time by torch/numpy.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the whole repo (secrets, venvs, caches, etc. are excluded via
# .dockerignore) so behaviour matches a normal local checkout.
COPY . .

# requirements.txt starts with `-e .`, which installs this repo itself in
# editable mode using setup.py — that's why the full source is copied first.
# The pip cache mount keeps rebuilds fast even though COPY-then-install means
# any source change invalidates this layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# The API listens on this port inside the container; publish it to reach the
# app from the host, e.g.: docker run -p 8000:8000 ...
EXPOSE 8000
ENV PORT=8000

# Required at runtime (no default, the app will fail to start without it):
#   GRID_DB_DSN or DATABASE_URL — e.g.
#   -e GRID_DB_DSN=postgresql://user:pass@host.docker.internal:5432/gridarena
# Optional at runtime:
#   REDIS_URL      (digital twin message broker; defaults to redis://localhost:6379,
#                   which will NOT resolve inside the container — override it)
#   LLM_API_KEY, LLM_API_URL, LLM_MODEL, LLM_VERIFY_SSL  (Chat Assistant)
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','8000') + '/docs', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn gridarena.app:app --host 0.0.0.0 --port ${PORT}"]

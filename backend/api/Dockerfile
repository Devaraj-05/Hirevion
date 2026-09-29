# syntax=docker/dockerfile:1
# The Hirevion API image. Build it from the repository root:
#   docker build -f backend/api/Dockerfile -t hirevion-api .
# Locally the API runs natively (`uv run hv api`); this image is what CI proves and the cloud runs.

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Every workspace member's pyproject.toml is needed to check the lock; only core and api ship.
COPY pyproject.toml uv.lock ./
COPY tools/devcli/pyproject.toml tools/devcli/
COPY tools/voice_bench/pyproject.toml tools/voice_bench/
COPY backend/interview_agent/pyproject.toml backend/interview_agent/
COPY backend/core backend/core
COPY backend/api backend/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package hirevion-api

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hirevion
COPY --from=build /app/.venv /app/.venv
COPY backend/migrations /app/migrations
ENV PATH="/app/.venv/bin:$PATH" \
    HV_MIGRATIONS_DIR=/app/migrations \
    PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"]
CMD ["uvicorn", "hirevion_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

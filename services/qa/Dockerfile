# syntax=docker/dockerfile:1.7
# Build from the repo root:  docker build -f services/qa/Dockerfile -t compliancewatch-qa .
ARG PYTHON_VERSION=3.12

# ---- builder: resolve and install into /app/.venv with uv --------------------------------------
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Layer 1: third-party dependencies only. Manifests of every member this package can depend on
# must be present for workspace discovery; --frozen tolerates the members that are not copied.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/py-common/pyproject.toml packages/py-common/
COPY packages/domain-kernel/pyproject.toml packages/domain-kernel/
COPY packages/ontology/pyproject.toml packages/ontology/
COPY services/qa/pyproject.toml services/qa/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package compliancewatch-qa

# Layer 2: workspace sources, installed non-editable so the venv is self-contained.
COPY packages/py-common/ packages/py-common/
COPY packages/domain-kernel/ packages/domain-kernel/
COPY packages/ontology/ packages/ontology/
COPY services/qa/ services/qa/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package compliancewatch-qa

# ---- runtime: same Debian base, no uv, non-root ------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Alembic needs the scripts at runtime (pre-sync migration job: alembic -c alembic.ini upgrade head)
COPY --from=builder --chown=app:app /app/services/qa/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/services/qa/migrations /app/migrations
# The plan and answer prompts, read when the app starts and by the readiness check.
COPY --from=builder --chown=app:app /app/services/qa/prompts /app/prompts
ENV CW_QA_PROMPTS_DIR=/app/prompts
USER app
EXPOSE 8000
CMD ["uvicorn", "qa.main:app", "--host", "0.0.0.0", "--port", "8000"]

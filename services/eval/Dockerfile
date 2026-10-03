# syntax=docker/dockerfile:1.7
# Build from the repo root:  docker build -f services/eval/Dockerfile -t compliancewatch-eval .
#
# A run starts the eval harness (evals/harness, `python -m cw_evals`), which scores the pipeline,
# the gateway and the qa, rulebook, profile and obligation services in process. Those read their
# prompts and data next to their sources (services/<name>/prompts, evals/golden), so this image
# installs the workspace editable and keeps the sources at the paths the venv points to.
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
COPY packages/contracts/clients/python/pyproject.toml packages/contracts/clients/python/
COPY evals/harness/pyproject.toml evals/harness/
COPY services/pipeline/pyproject.toml services/pipeline/
COPY services/llm-gateway/pyproject.toml services/llm-gateway/
COPY services/qa/pyproject.toml services/qa/
COPY services/rulebook/pyproject.toml services/rulebook/
COPY services/profile/pyproject.toml services/profile/
COPY services/obligation/pyproject.toml services/obligation/
COPY services/eval/pyproject.toml services/eval/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package compliancewatch-eval

# Layer 2: workspace sources, installed editable (see the top of this file).
COPY packages/py-common/ packages/py-common/
COPY packages/domain-kernel/ packages/domain-kernel/
COPY packages/ontology/ packages/ontology/
COPY packages/contracts/clients/python/ packages/contracts/clients/python/
COPY evals/harness/ evals/harness/
COPY evals/golden/ evals/golden/
COPY services/pipeline/ services/pipeline/
COPY services/llm-gateway/ services/llm-gateway/
COPY services/qa/ services/qa/
COPY services/rulebook/ services/rulebook/
COPY services/profile/ services/profile/
COPY services/obligation/ services/obligation/
COPY services/eval/ services/eval/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package compliancewatch-eval

# ---- runtime: same Debian base, no uv, non-root ------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/packages /app/packages
COPY --from=builder --chown=app:app /app/evals /app/evals
COPY --from=builder --chown=app:app /app/services /app/services
# Alembic needs the scripts at runtime (pre-sync migration job: alembic -c alembic.ini upgrade head)
COPY --from=builder --chown=app:app /app/services/eval/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/services/eval/migrations /app/migrations
ENV CW_EVAL_GOLDEN_DIR=/app/evals/golden
USER app
EXPOSE 8000
CMD ["uvicorn", "eval_service.main:app", "--host", "0.0.0.0", "--port", "8000"]

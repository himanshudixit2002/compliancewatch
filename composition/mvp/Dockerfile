# syntax=docker/dockerfile:1.7
# Build from the repo root:  docker build -f composition/mvp/Dockerfile -t compliancewatch-mvp .
#
# The one deployable of ADR-013 (composition/mvp/README.md, "The image"): one image, run by
# command as the app process (`cw-mvp serve`, the default), the worker process (`cw-mvp worker`)
# and the release step (`cw-mvp release`; `cw-mvp migrate`, `topics` and `check-config` alone).
#
# The services read files beside their sources at runtime: the gateway's prompt registry, the qa
# and pipeline prompts, the rulebook's seed calendar, every service's alembic.ini and migrations,
# and composition/mvp/topics.toml; the eval service runs the harness (evals/harness) in a child
# process on the golden set (evals/golden). So, as the eval image does, the workspace is installed
# editable and the sources stay at the paths the venv points to. The ontology's YAML and the
# contracts client are inside their packages. Tests, docs, the web app and every .env stay out of
# the build context (.dockerignore); the image holds no secret.
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
COPY services/identity/pyproject.toml services/identity/
COPY services/profile/pyproject.toml services/profile/
COPY services/rulebook/pyproject.toml services/rulebook/
COPY services/applicability-engine/pyproject.toml services/applicability-engine/
COPY services/obligation/pyproject.toml services/obligation/
COPY services/notification/pyproject.toml services/notification/
COPY services/qa/pyproject.toml services/qa/
COPY services/llm-gateway/pyproject.toml services/llm-gateway/
COPY services/eval/pyproject.toml services/eval/
COPY services/pipeline/pyproject.toml services/pipeline/
COPY composition/mvp/pyproject.toml composition/mvp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package compliancewatch-mvp

# Layer 2: workspace sources, installed editable (see the top of this file).
COPY packages/py-common/ packages/py-common/
COPY packages/domain-kernel/ packages/domain-kernel/
COPY packages/ontology/ packages/ontology/
COPY packages/contracts/clients/python/ packages/contracts/clients/python/
COPY evals/harness/ evals/harness/
COPY evals/golden/ evals/golden/
COPY services/ services/
COPY composition/mvp/ composition/mvp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package compliancewatch-mvp

# ---- runtime: same Debian base, no uv, non-root, code owned by root ----------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages /app/packages
COPY --from=builder /app/evals /app/evals
COPY --from=builder /app/services /app/services
COPY --from=builder /app/composition /app/composition
USER app
# Public listener, internal listener, the worker's health.
EXPOSE 8000 8080 8001
CMD ["cw-mvp", "serve"]

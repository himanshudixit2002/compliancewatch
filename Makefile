# ComplianceWatch root Makefile (guide section 13: make dev, make test, make eval, make migrate).
# GNU make 3.81 (macOS default) compatible: no .ONESHELL / .SHELLFLAGS / != / $(file). Recipe lines start with a TAB.
# `make help` lists every target; `##` comments after a target are its help text.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
COMPOSE := docker compose
PROFILES := --profile observability --profile llm
SERVICE ?=
COV_FAIL_UNDER ?= 80
# testcontainers starts a reaper container that bind-mounts the Docker socket. With Colima (or any
# VM-based daemon) the host-side socket path does not exist inside the VM, so name the daemon-side
# path; a value of the same name in the environment still wins.
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE ?= /var/run/docker.sock

# ---- Inventory -------------------------------------------------------------------------------
SERVICES := identity profile rulebook applicability-engine obligation notification qa llm-gateway eval pipeline
PY_PACKAGES := py-common domain-kernel ontology
PY_DIRS := $(addprefix packages/,$(PY_PACKAGES)) packages/contracts/clients/python $(addprefix services/,$(SERVICES)) evals/harness tools/demo composition/mvp

# Service directory -> import package (two exceptions avoid shadowing stdlib/builtins).
PKG_profile := profile_service
PKG_eval := eval_service
PKG = $(or $(PKG_$(SERVICE)),$(subst -,_,$(SERVICE)))
# Service directory -> Postgres schema (infra/dev/postgres/init.sql).
SCHEMA_applicability-engine := applicability
SCHEMA_llm-gateway := llm_gateway
SCHEMA = $(or $(SCHEMA_$(SERVICE)),$(SERVICE))
# Local dev ports for `make run`; containers always listen on 8000.
PORT_identity := 8001
PORT_profile := 8002
PORT_rulebook := 8003
PORT_applicability-engine := 8004
PORT_obligation := 8005
PORT_notification := 8006
PORT_qa := 8007
PORT_llm-gateway := 8008
PORT_eval := 8009
PORT_pipeline := 8010
PORT ?= $(or $(PORT_$(SERVICE)),8000)

# ---- Help ------------------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:[^#]*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":[^#]*## "} {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Tool guards -----------------------------------------------------------------------------
.PHONY: check-docker-cli check-docker check-uv check-pnpm doctor
check-docker-cli:
	@command -v docker >/dev/null 2>&1 || { \
	  echo "error: 'docker' is not on PATH."; \
	  echo "  Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/"; \
	  echo "  Homebrew:       brew install colima docker docker-compose docker-buildx && colima start --cpu 4 --memory 8"; \
	  echo "  See docs/onboarding/local-dev.md"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { \
	  echo "error: the 'docker compose' plugin is missing. With Homebrew, add to ~/.docker/config.json:"; \
	  echo '  {"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}'; exit 1; }

check-docker: check-docker-cli
	@docker info >/dev/null 2>&1 || { echo "error: Docker daemon not reachable. Start Docker Desktop or run 'colima start'."; exit 1; }

check-uv:
	@command -v uv >/dev/null 2>&1 || { echo "error: 'uv' not found. Install: brew install uv"; exit 1; }

check-pnpm:
	@command -v pnpm >/dev/null 2>&1 || { echo "error: 'pnpm' not found. Install: brew install pnpm"; exit 1; }

doctor: ## Print which required tools are present
	@for t in docker uv pnpm node python3 actionlint gitleaks pre-commit; do \
	  if command -v $$t >/dev/null 2>&1; then printf "  %-10s %s\n" "$$t" "$$(command -v $$t)"; \
	  else printf "  %-10s MISSING\n" "$$t"; fi; \
	done

# ---- Local stack (guide section 17) ---------------------------------------------------------
.PHONY: dev dev-observability dev-llm dev-urls dev-down dev-reset dev-logs dev-ps dev-psql compose-config
dev: check-docker ## Start Postgres, Redis, Redpanda, Temporal (+UI); waits for health, prints endpoints
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example"; }
	$(COMPOSE) up -d --wait --wait-timeout 180
	@$(MAKE) --no-print-directory dev-urls

dev-observability: check-docker ## Same as dev plus Langfuse, OTel collector, Prometheus, Tempo, Grafana (compose profile: observability)
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example"; }
	$(COMPOSE) --profile observability up -d --wait --wait-timeout 240
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	curl -sf "http://localhost:$${OTEL_HEALTH_PORT:-13133}/" >/dev/null && echo "otel-collector healthy" || { echo "error: otel-collector health check failed"; exit 1; }
	@$(MAKE) --no-print-directory dev-urls

dev-llm: check-docker ## Build and start the fake LLM gateway container (compose profile: llm)
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example"; }
	$(COMPOSE) --profile llm up -d --build --wait --wait-timeout 180 fake-llm
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	echo "  fake LLM gateway http://localhost:$${FAKE_LLM_PORT:-8090}/health"

dev-urls:
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	echo ""; echo "ComplianceWatch dev stack"; \
	echo "  Postgres         localhost:$${POSTGRES_PORT:-5432}   db=$${POSTGRES_DB:-compliancewatch} user=$${POSTGRES_USER:-cw}"; \
	echo "  Redis            localhost:$${REDIS_PORT:-6379}"; \
	echo "  Kafka (Redpanda) localhost:$${REDPANDA_KAFKA_PORT:-19092}   schema registry http://localhost:$${REDPANDA_SCHEMA_REGISTRY_PORT:-18081}"; \
	echo "  Temporal         localhost:$${TEMPORAL_PORT:-7233}   UI http://localhost:$${TEMPORAL_UI_PORT:-8233}"; \
	echo "  Langfuse         http://localhost:$${LANGFUSE_PORT:-3010}   (make dev-observability only)"; \
	echo "  OTel collector   localhost:$${OTEL_GRPC_PORT:-4317} gRPC, $${OTEL_HTTP_PORT:-4318} HTTP   (make dev-observability only; CW_OTEL_ENDPOINT=http://localhost:$${OTEL_GRPC_PORT:-4317})"; \
	echo "  Prometheus       http://localhost:$${PROMETHEUS_PORT:-9090}   (make dev-observability only)"; \
	echo "  Grafana          http://localhost:$${GRAFANA_PORT:-3030}   (make dev-observability only; dashboard: ComplianceWatch services)"; \
	echo "  Fake LLM gateway http://localhost:$${FAKE_LLM_PORT:-8090}   (make dev-llm only)"; \
	echo "Next: make migrate"

dev-down: check-docker ## Stop the stack, keep volumes
	$(COMPOSE) $(PROFILES) down --remove-orphans

dev-reset: check-docker ## Stop the stack and delete volumes (infra/dev/postgres/init.sql runs again on next make dev)
	$(COMPOSE) $(PROFILES) down --volumes --remove-orphans

dev-logs: check-docker ## Tail logs; one service with SERVICE=postgres
	$(COMPOSE) $(PROFILES) logs --follow --tail=100 $(SERVICE)

dev-ps: check-docker ## Container status and health
	$(COMPOSE) $(PROFILES) ps

dev-psql: check-docker ## psql into the application database
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

dev-backup: check-docker ## pg_dump the dev database into var/backups/<timestamp>.dump
	@mkdir -p var/backups; stamp=$$(date -u +%Y%m%dT%H%M%SZ); \
	$(COMPOSE) exec -T postgres pg_dump -U $${POSTGRES_USER:-cw} -Fc $${POSTGRES_DB:-compliancewatch} > var/backups/$$stamp.dump && echo "wrote var/backups/$$stamp.dump"

dev-restore: check-docker ## Restore the dev database from a dump: make dev-restore FILE=var/backups/x.dump
	@[ -n "$(FILE)" ] || { echo "usage: make dev-restore FILE=var/backups/<stamp>.dump"; exit 1; }
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-cw} -d postgres -c "DROP DATABASE IF EXISTS $${POSTGRES_DB:-compliancewatch} WITH (FORCE)" -c "CREATE DATABASE $${POSTGRES_DB:-compliancewatch}"
	$(COMPOSE) exec -T postgres pg_restore -U $${POSTGRES_USER:-cw} -d $${POSTGRES_DB:-compliancewatch} --no-owner < $(FILE) && echo "restored $(FILE)"

compose-config: check-docker-cli ## Validate docker-compose.yml (CLI only, no daemon needed)
	$(COMPOSE) $(PROFILES) config --quiet && echo "docker-compose.yml OK"

# ---- Python: uv workspace (guide section 12) -------------------------------------------------
.PHONY: py-sync lock-check py-lint py-format py-typecheck py-test py-test-integration importlint
py-sync: check-uv ## Sync the Python workspace into .venv
	$(UV) sync --all-packages

lock-check: check-uv ## Fail if uv.lock is out of date with the pyproject files
	$(UV) lock --check

py-lint: check-uv ## ruff check and ruff format --check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

py-format: check-uv ## ruff format and ruff check --fix
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

py-typecheck: check-uv ## mypy --strict per package (src, tests, migrations/env.py), the root conftest and the repo scripts
	@status=0; \
	for d in $(PY_DIRS); do \
	  targets="$$d/src"; \
	  [ -d "$$d/tests" ] && targets="$$targets $$d/tests"; \
	  [ -f "$$d/migrations/env.py" ] && targets="$$targets $$d/migrations/env.py"; \
	  echo "mypy $$targets"; \
	  $(UV) run mypy $$targets || status=1; \
	done; \
	$(UV) run mypy conftest.py packages/contracts/scripts infra/scripts || status=1; \
	exit $$status

py-test: check-uv ## pytest: unit and contract tests with the coverage gate (no Docker needed)
	$(UV) run pytest -m "not integration" --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-fail-under=$(COV_FAIL_UNDER)

py-test-integration: check-uv ## testcontainers tests; skipped gracefully when Docker is absent
	@if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then \
	  echo "docker is not available: skipping integration tests"; exit 0; fi
	TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=$(TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE) $(UV) run pytest -m integration

importlint: check-uv ## import-linter contracts: no cross-service imports, domain imports no I/O
	$(UV) run lint-imports

# ---- TypeScript: pnpm + Turborepo -----------------------------------------------------------
.PHONY: ts-install ts-lint ts-format ts-typecheck ts-test ts-build ts-dev
ts-install: check-pnpm ## pnpm install --frozen-lockfile
	$(PNPM) install --frozen-lockfile

ts-lint: check-pnpm ## eslint per package (turbo, cached) + prettier check
	$(PNPM) turbo run lint
	$(PNPM) format

ts-format: check-pnpm ## prettier --write
	$(PNPM) format:write

ts-typecheck: check-pnpm ## tsc --noEmit (strict) per package via turbo
	$(PNPM) turbo run typecheck

ts-test: check-pnpm ## vitest run --coverage per package (thresholds in each vitest.config)
	$(PNPM) turbo run test

ts-build: check-pnpm ## next build + tsc build
	$(PNPM) turbo run build

ts-dev: check-pnpm ## next dev (:3000) and whatsapp-bot (:8080) with reload
	$(PNPM) turbo run dev

# ---- Composition (guide sections 13, 17, 19) -------------------------------------------------
.PHONY: install lint format typecheck test check eval eval-check label demo runbooks-check migrate run worker relay seed openapi contracts contracts-check hooks ci-lint
# The gates `make check` runs. A package adds its own with `CHECKS += <target>` in its section.
# The prerequisites of check expand a second time when make runs them (.SECONDEXPANSION below),
# so a `CHECKS +=` line counts wherever it sits in this file.
CHECKS := lint typecheck test importlint lock-check contracts-check runbooks-check

install: py-sync ts-install ## Install both toolchains

lint: py-lint ts-lint ## Lint both sides (CI step 1)

format: py-format ts-format ## Auto-format both sides

typecheck: py-typecheck ts-typecheck ## mypy --strict and tsc --strict (CI step 1)

test: py-test ts-test ## Unit and contract tests on both sides (CI step 2)

.SECONDEXPANSION:
check: $$(CHECKS) ## Everything CI runs before integration tests (the gates listed in CHECKS)

runbooks-check: check-uv ## Every Prometheus alert links an existing runbook (guide section 18)
	$(UV) run python infra/scripts/check_alert_runbooks.py

EVAL_PROFILE ?= ci
eval: check-uv ## Eval harness against evals/golden: make eval [EVAL_PROFILE=ci|nightly] [ARGS="--provider fake --suite qa"]
	$(UV) run --package compliancewatch-evals eval-harness --profile $(EVAL_PROFILE) $(ARGS)

eval-check: check-uv ## KAG golden set and world well formed: quotes, seed supports, scripted plans and answers
	CW_LOG_LEVEL=WARNING $(UV) run --package compliancewatch-evals eval-golden-check $(ARGS)

demo: check-uv ## The demo tenant end to end in one process (consent, profile, rules, obligations, reminder): make demo [ARGS=--json]
	CW_LOG_LEVEL=WARNING $(UV) run --package compliancewatch-demo cw-demo --daytime $(ARGS)

label: check-uv ## Labelling tool: make label ARGS="check" | "index --source cbic_notifications --since 2024-01-01 --out evals/golden/extraction/cbic_notifications/index.yaml" | "prepare --index ..."
	$(UV) run --package compliancewatch-pipeline pipeline-label $(ARGS)

migrate: check-uv ## alembic upgrade head for every service, or one: make migrate SERVICE=identity
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	for svc in $(if $(SERVICE),$(SERVICE),$(SERVICES)); do \
	  case "$$svc" in \
	    applicability-engine) schema=applicability ;; \
	    llm-gateway) schema=llm_gateway ;; \
	    *) schema=$$svc ;; \
	  esac; \
	  url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$${schema}%2Cpublic"; \
	  echo "==> $$svc: alembic upgrade head (schema $$schema)"; \
	  CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$$schema" \
	    $(UV) run --package compliancewatch-$$svc alembic -c services/$$svc/alembic.ini upgrade head || exit 1; \
	done

# run and worker name the process's service client after the service (CW_SERVICE_CLIENT_ID) unless
# .env or the environment sets it, so a worker is its service's client; elsewhere an empty id stands
# for the process's service name. No token is sent until CW_SERVICE_CLIENT_SECRET is set too.
run: check-uv ## Run one service with reload: make run SERVICE=identity [PORT=8001]
	@[ -n "$(SERVICE)" ] || { echo "usage: make run SERVICE=<identity|profile|...> [PORT=8000]"; exit 1; }
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$(SCHEMA)%2Cpublic"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" CW_SERVICE_CLIENT_ID="$${CW_SERVICE_CLIENT_ID:-$(SERVICE)}" \
	  $(UV) run --package compliancewatch-$(SERVICE) uvicorn $(PKG).main:app --reload --port $(PORT) \
	    --reload-dir services/$(SERVICE)/src --reload-dir packages/py-common/src \
	    --reload-dir packages/domain-kernel/src --reload-dir packages/ontology/src

seed: check-uv ## Load the rulebook seed calendar as draft rule versions: make seed SERVICE=rulebook [ARGS=--check]
	@[ -n "$(SERVICE)" ] || { echo "usage: make seed SERVICE=rulebook [ARGS=--check]"; exit 1; }
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$(SCHEMA)%2Cpublic"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" \
	  $(UV) run --package compliancewatch-$(SERVICE) $(SERVICE)-seed $(ARGS)

backfill: check-uv ## Backfill one regulator source into var/raw: make backfill SERVICE=pipeline ARGS="--source cbic_notifications --since 2026-01-01"
	@[ "$(SERVICE)" = "pipeline" ] || { echo "usage: make backfill SERVICE=pipeline ARGS=\"--source <key> [--since YYYY-MM-DD] [--limit N] [--list-only]\""; exit 1; }
	@$(UV) run --package compliancewatch-pipeline pipeline-backfill $(ARGS)

worker: check-uv ## Run a service's worker process, python -m <pkg>.worker (consumers, relay, periodic jobs, Temporal): make worker SERVICE=pipeline
	@[ -n "$(SERVICE)" ] || { echo "usage: make worker SERVICE=<pipeline|notification|...>"; exit 1; }
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$(SCHEMA)%2Cpublic"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" CW_SERVICE_CLIENT_ID="$${CW_SERVICE_CLIENT_ID:-$(SERVICE)}" \
	  $(UV) run --package compliancewatch-$(SERVICE) python -m $(PKG).worker

relay: check-uv ## Run the outbox relay for one service's schema: make relay SERVICE=obligation
	@[ -n "$(SERVICE)" ] || { echo "usage: make relay SERVICE=<identity|profile|...>"; exit 1; }
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$(SCHEMA)%2Cpublic"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" \
	  $(UV) run --package compliancewatch-$(SERVICE) python -m py_common.outbox

openapi: check-uv ## Export a service's OpenAPI spec: make openapi SERVICE=llm-gateway -> packages/contracts/openapi/<svc>.v1.json
	@[ -n "$(SERVICE)" ] || { echo "usage: make openapi SERVICE=<identity|profile|...>"; exit 1; }
	$(UV) run --package compliancewatch-$(SERVICE) python -c "import json, pathlib; from $(PKG).main import app; pathlib.Path('packages/contracts/openapi/$(SERVICE).v1.json').write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n', encoding='utf-8')"
	@echo "wrote packages/contracts/openapi/$(SERVICE).v1.json"

contracts: check-uv check-pnpm ## Generate the event clients (pydantic + TypeScript) and the Python REST models (openapi/clients.json)
	$(UV) run python packages/contracts/scripts/generate_events.py
	$(UV) run python packages/contracts/scripts/generate_rest.py

contracts-check: check-uv check-pnpm ## Event schemas pass the 2020-12 metaschema, every topic in code has one, the generated clients match them, and public.v1.json is current
	$(UV) run check-jsonschema --check-metaschema packages/contracts/events/schemas/*.json
	$(UV) run python packages/contracts/scripts/check_topics.py
	$(UV) run python packages/contracts/scripts/build_public_openapi.py --check
	@$(MAKE) --no-print-directory contracts
	@drift=$$(git status --porcelain -- packages/contracts/clients/python/src/cw_contracts/events packages/contracts/clients/typescript/events packages/contracts/clients/python/src/cw_contracts/rest); \
	if [ -n "$$drift" ]; then echo "$$drift"; echo "error: generated clients are out of date; commit the output of make contracts"; exit 1; fi
	@echo "contracts OK"

hooks: ## Install the pre-commit and commit-msg hooks
	pre-commit install --install-hooks

ci-lint: ## Validate GitHub Actions workflows and the pre-commit config without running them
	actionlint -color
	pre-commit validate-config

# ---- Migration lint (guide section 17: expand-contract; tenant isolation by row-level security)
.PHONY: migrations-check migrations-catalog
CHECKS += migrations-check

migrations-check: check-uv ## Migration files: one head per service, names match revisions, downgrades, marked contract steps
	$(UV) run python infra/scripts/check_migrations.py static

migrations-catalog: check-uv ## After make migrate: tenant tables have forced row-level security (rules in infra/scripts/migration_lint.toml)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	$(UV) run python infra/scripts/check_migrations.py catalog \
	  --dsn "postgresql://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}"

# ---- Alert rules (guide section 18) ---------------------------------------------------------
.PHONY: alerts-check
# promtool from the Prometheus image the compose stack runs, so the rules are checked by the same
# version that loads them.
PROMETHEUS_IMAGE = $(shell awk '/image: prom\/prometheus:/ { print $$2; exit }' docker-compose.yml)
PROMTOOL = docker run --rm --entrypoint promtool -v "$(CURDIR)/infra/dev/prometheus:/rules:ro" $(PROMETHEUS_IMAGE)

alerts-check: check-docker ## promtool: alert rules parse and their unit tests pass (infra/dev/prometheus/alerts.test.yml)
	$(PROMTOOL) check rules /rules/alerts.yml
	$(PROMTOOL) test rules /rules/alerts.test.yml

# ---- OpenAPI gates (guide section 17 step 3: every endpoint has a schema and a contract test)
.PHONY: openapi-check openapi-compat
CHECKS += openapi-check
BASE ?= origin/main

openapi-check: check-uv ## Every service that serves API routes commits its spec and a contract test
	@status=0; \
	for svc in $(SERVICES); do \
	  CW_LOG_LEVEL=WARNING $(UV) run --package compliancewatch-$$svc \
	    python packages/contracts/scripts/check_openapi_coverage.py services/$$svc || status=1; \
	done; \
	exit $$status

openapi-compat: check-uv ## Committed specs break no client of a base ref: make openapi-compat [BASE=origin/main]
	$(UV) run python packages/contracts/scripts/check_openapi_compat.py --base-ref $(BASE)

# ---- Security scans (guide section 17: SAST and dependency scanning) -------------------------
.PHONY: sast deps-scan
# Pinned images. The sast CI job runs this target; the dependency-scan job runs the same Trivy
# version through its action, so bump both together.
SEMGREP_IMAGE := semgrep/semgrep:1.178.0
TRIVY_IMAGE := aquasec/trivy:0.74.0
SEMGREP_PACKS := p/python p/typescript p/dockerfile p/github-actions
SEMGREP = docker run --rm -v "$(CURDIR):/src" --workdir /src $(SEMGREP_IMAGE) semgrep

sast: check-docker ## Semgrep: registry packs and the rules in .semgrep; an ERROR finding fails (writes semgrep.sarif)
	$(SEMGREP) scan $(addprefix --config ,$(SEMGREP_PACKS)) --config .semgrep \
	  --metrics off --severity ERROR --error --sarif-output=semgrep.sarif
	$(SEMGREP) --test --metrics off --config .semgrep/cw.yml .semgrep/cw.py

deps-scan: check-docker ## Trivy: fixable HIGH and CRITICAL vulnerabilities and misconfigurations (settings in .trivy.yaml)
	docker run --rm -v "$(CURDIR):/src:ro" --workdir /src -v compliancewatch-trivy-cache:/root/.cache/trivy \
	  $(TRIVY_IMAGE) fs --config .trivy.yaml .

# ---- CI gate (the one check branch protection requires) ------------------------------------
.PHONY: ci-gate-check
CHECKS += ci-gate-check

ci-gate-check: check-uv ## Every ci.yml job is in the needs of the required "CI gate" job
	$(UV) run python infra/scripts/check_ci_gate.py

# ---- Rulebook data quality (checks over versions, citations and relations) --------------------
.PHONY: data-quality
# Not in CHECKS: it reads a database. make exits 2 for any failed recipe, so the nightly job calls
# rulebook-quality directly with the environment below (keep the two in step) to tell violations
# (1) from an unreadable database (2); it runs after migrate and seed, or against
# CW_DQ_DATABASE_URL (a read-only role on a deployed rulebook) when that is set.
data-quality: check-uv ## Rulebook data-quality checks on the local rulebook schema, or CW_DQ_DATABASE_URL: make data-quality [ARGS=--json]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="$${CW_DQ_DATABASE_URL:-postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}}"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA=rulebook CW_LOG_LEVEL=WARNING \
	  $(UV) run --package compliancewatch-rulebook rulebook-quality $(ARGS)

# ---- Feature flags (packages/flags/registry.json) -------------------------------------------
.PHONY: flags flags-check dev-flags
CHECKS += flags-check
# dev-down and dev-reset stop the Unleash container too.
PROFILES += --profile flags

flags: check-uv ## Write py-common's copy of the flag registry, then run flags-check
	$(UV) run python infra/scripts/check_flags.py write

flags-check: check-uv ## Flag registry: schema, owners, expiry, bool defaults off, py-common copy current, every switch in settings registered
	$(UV) run python infra/scripts/check_flags.py check

dev-flags: check-docker ## Start Unleash for CW_FLAGS_PROVIDER=unleash (compose profile: flags); creates its database when missing
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example"; }
	$(COMPOSE) up -d --wait --wait-timeout 180 postgres
	$(COMPOSE) exec -T postgres sh -c 'psql -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < infra/dev/postgres/40-unleash.sql
	$(COMPOSE) --profile flags up -d --wait --wait-timeout 180 unleash
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	echo "  Unleash http://localhost:$${UNLEASH_PORT:-4242} (first login admin / unleash4all)"; \
	echo "  CW_FLAGS_PROVIDER=unleash CW_UNLEASH_URL=http://localhost:$${UNLEASH_PORT:-4242}/api CW_UNLEASH_API_TOKEN=<the client token in docker-compose.yml>"

# ---- Public API spec (guide section 10) -------------------------------------------------------
.PHONY: openapi-public
# contracts-check fails while packages/contracts/openapi/public.v1.json differs from this build or
# the committed REST models differ from what make contracts generates from it.

openapi-public: check-uv ## Merge the operations the services tag public into packages/contracts/openapi/public.v1.json (after make openapi SERVICE=x), then regenerate the Python REST models
	$(UV) run python packages/contracts/scripts/build_public_openapi.py
	$(UV) run python packages/contracts/scripts/generate_rest.py

# ---- Web app (apps/web, packages/ui) ---------------------------------------------------------
.PHONY: control-panel control-panel-app web-dev web-stack web-stack-wait web-stack-down web-stack-logs web-seed web-e2e-install web-e2e web-screens web-screens-check openapi-ts openapi-ts-check
CHECKS += web-screens-check openapi-ts-check
# The port comes from WEB_PORT in .env (3000 unless the file says otherwise); a value already in
# the environment wins, as for every variable the recipes source.

web-dev: check-pnpm ## next dev on WEB_PORT from .env; /admin lists the internal tools, /design the UI kit
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	PORT=$${WEB_PORT:-3000} $(PNPM) --filter web dev

# The UI-only stack: the services behind the web app as ten separate processes with no worker,
# so no decision becomes obligations or a message here (make product, below, is the full
# product). Every service on SERVICE_PORT_BASE+1 .. +10 in the SERVICES order (8001-8010 unless
# .env moves the base; a second clone sets 9200), started with nohup, pids and logs under
# var/web-stack. The stack is defined here rather than inherited from .env so a fresh
# clone and CI see the same states: memory stores (no container), the profile's built-in static
# GSTIN lookup (the demo GSTIN pre-fills), the billing provider "none" (subscribe answers 503;
# BILLING=memory starts subscriptions in memory for a manual demo, and make web-e2e takes the
# same BILLING so the billing spec expects that state), the KAG layer off, the inter-service URLs
# on the same base, and the rulebook's two tokens from .env or the placeholders local-write-token
# and local-review-token (not secrets), as make product passes them. The rulebook publishes
# (CW_RULEBOOK_PUBLISH_ENABLED=true) and, on the memory store, starts with the seed calendar's
# drafts (CW_RULEBOOK_SEED_ON_START, local and test only), so the web app's rule versions and
# publish workflow have versions to show; every draft still needs review, and only an analyst's
# steps through the web app move one. Memory stores lose their rows when the stack stops;
# STORE=postgres runs every store on the compose Postgres instead (make dev, make migrate and
# make seed SERVICE=rulebook first), with the schema search path make run uses.
WEB_STACK_DIR := var/web-stack
WEB_STACK_WAIT_SECONDS ?= 60
STORE ?= memory
BILLING ?= none

web-stack: check-uv ## UI-only stack, no worker: every service on SERVICE_PORT_BASE+1..10 with memory stores (pids and logs in var/web-stack): make web-stack [STORE=postgres] [BILLING=memory]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	[ "$(STORE)" = "memory" ] || [ "$(STORE)" = "postgres" ] || { echo "usage: make web-stack [STORE=memory|postgres]"; exit 1; }; \
	[ "$(BILLING)" = "none" ] || [ "$(BILLING)" = "memory" ] || { echo "usage: make web-stack [BILLING=none|memory]"; exit 1; }; \
	mkdir -p $(WEB_STACK_DIR); base=$${SERVICE_PORT_BASE:-8000}; i=0; \
	token="$${CW_RULEBOOK_WRITE_TOKEN:-local-write-token}"; review="$${CW_RULEBOOK_REVIEW_TOKEN:-local-review-token}"; \
	seed=false; if [ "$(STORE)" = "memory" ]; then seed=true; fi; \
	echo "web stack: services on $$((base+1))-$$((base+10)), $(STORE) stores, billing provider $(BILLING), rulebook publishing on"; \
	for svc in $(SERVICES); do \
	  i=$$((i+1)); port=$$((base+i)); pidfile=$(WEB_STACK_DIR)/$$svc.pid; \
	  if [ -f "$$pidfile" ] && kill -0 "$$(cat "$$pidfile")" 2>/dev/null; then \
	    echo "  $$svc already running (pid $$(cat "$$pidfile")) on http://localhost:$$port"; continue; fi; \
	  case "$$svc" in profile) pkg=profile_service ;; eval) pkg=eval_service ;; *) pkg=$$(echo "$$svc" | tr - _) ;; esac; \
	  case "$$svc" in applicability-engine) schema=applicability ;; llm-gateway) schema=llm_gateway ;; *) schema=$$svc ;; esac; \
	  url="$${CW_DATABASE_URL:-}"; \
	  if [ "$(STORE)" = "postgres" ]; then \
	    url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$${schema}%2Cpublic"; \
	  fi; \
	  CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$$schema" \
	  CW_IDENTITY_STORE=$(STORE) CW_PROFILE_STORE=$(STORE) CW_RULEBOOK_STORE=$(STORE) CW_OBLIGATION_STORE=$(STORE) CW_NOTIFICATION_STORE=$(STORE) CW_EVAL_STORE=$(STORE) CW_APPLICABILITY_ENGINE_STORE=$(STORE) CW_LLM_LEDGER=$(STORE) \
	  CW_PROFILE_GSTIN_LOOKUP=static CW_BILLING_PROVIDER=$(BILLING) CW_RULEBOOK_PUBLISH_ENABLED=true CW_QA_KAG_ENABLED=false \
	  CW_RULEBOOK_SEED_ON_START=$$seed CW_RULEBOOK_WRITE_TOKEN="$$token" CW_RULEBOOK_REVIEW_TOKEN="$$review" \
	  CW_PROFILE_URL="http://localhost:$$((base+2))" CW_RULEBOOK_URL="http://localhost:$$((base+3))" \
	  CW_OBLIGATION_URL="http://localhost:$$((base+5))" CW_LLM_GATEWAY_URL="http://localhost:$$((base+8))" \
	  nohup $(UV) run --package compliancewatch-$$svc uvicorn $$pkg.main:app --host 127.0.0.1 --port $$port \
	    > $(WEB_STACK_DIR)/$$svc.log 2>&1 & \
	  echo $$! > "$$pidfile"; \
	  echo "  $$svc  http://localhost:$$port  (log $(WEB_STACK_DIR)/$$svc.log)"; \
	done; \
	echo "Next: make web-stack-wait, then make web-seed"

web-stack-wait: ## Wait until every web-stack service answers /health (WEB_STACK_WAIT_SECONDS, default 60)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	base=$${SERVICE_PORT_BASE:-8000}; deadline=$$((SECONDS + $(WEB_STACK_WAIT_SECONDS))); status=0; i=0; \
	for svc in $(SERVICES); do \
	  i=$$((i+1)); port=$$((base+i)); \
	  until curl -sf "http://localhost:$$port/health" >/dev/null 2>&1; do \
	    if [ $$SECONDS -ge $$deadline ]; then break; fi; sleep 0.5; \
	  done; \
	  if curl -sf "http://localhost:$$port/health" >/dev/null 2>&1; then echo "  $$svc healthy on http://localhost:$$port"; \
	  else echo "error: $$svc did not answer on http://localhost:$$port/health (see $(WEB_STACK_DIR)/$$svc.log)"; status=1; fi; \
	done; \
	exit $$status

web-stack-down: ## Stop the web-stack services and remove their pid files (logs stay in var/web-stack)
	@for pidfile in $(WEB_STACK_DIR)/*.pid; do \
	  [ -f "$$pidfile" ] || continue; \
	  svc=$$(basename "$$pidfile" .pid); pid=$$(cat "$$pidfile"); \
	  if kill -0 "$$pid" 2>/dev/null; then \
	    pkill -TERM -P "$$pid" 2>/dev/null; kill -TERM "$$pid" 2>/dev/null; \
	    n=0; while kill -0 "$$pid" 2>/dev/null && [ $$n -lt 20 ]; do n=$$((n+1)); sleep 0.25; done; \
	    if kill -0 "$$pid" 2>/dev/null; then pkill -KILL -P "$$pid" 2>/dev/null; kill -KILL "$$pid" 2>/dev/null; fi; \
	    echo "  $$svc stopped (pid $$pid)"; \
	  else echo "  $$svc was not running"; fi; \
	  rm -f "$$pidfile"; \
	done; true

control-panel: ## Open the click-to-run control panel window (tools/control-panel)
	@.venv/bin/python tools/control-panel/control_panel.py

control-panel-app: ## Build ComplianceWatch.app on the Desktop: make control-panel-app [DEST=~/Applications]
	@tools/control-panel/install-app.sh $(DEST)

web-stack-logs: ## Tail a web-stack service's log: make web-stack-logs SERVICE=identity (every log without SERVICE)
	@if [ -n "$(SERVICE)" ]; then tail -n 100 -f $(WEB_STACK_DIR)/$(SERVICE).log; \
	else for f in $(WEB_STACK_DIR)/*.log; do [ -f "$$f" ] || continue; echo "==> $$f"; tail -n 20 "$$f"; done; fi

# The demo tenant in the running stack, over the services' HTTP APIs (apps/web/scripts/seed): the
# owner's consents, the GSTIN registration with its pre-fill and answers, the WhatsApp preference,
# and one recorded CBIC notification with its clauses, mentions and relation candidate replayed
# from committed fixtures. It records the tenant in var/seed/last.json for the development
# sign-in and exits non-zero when any step fails. The service URLs are the CW_WEB_*_URL values in
# apps/web/.env.local, else SERVICE_PORT_BASE+1..10; the write token is the one make web-stack
# gives the rulebook (CW_RULEBOOK_WRITE_TOKEN from .env, else local-write-token).
web-seed: check-pnpm ## Seed the web-stack services with the demo tenant and a recorded notification: make web-seed [ARGS="--tenant <uuid> --json"]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	CW_WEB_RULEBOOK_WRITE_TOKEN="$${CW_WEB_RULEBOOK_WRITE_TOKEN:-$${CW_RULEBOOK_WRITE_TOKEN:-local-write-token}}" \
	$(PNPM) --silent --filter web seed $(ARGS)

web-e2e-install: check-pnpm ## Download Chromium for Playwright, once per machine (the package has no install script)
	$(PNPM) --filter web e2e:install

# The suite runs against the services make web-stack starts (then make web-stack-wait and make
# web-seed; CI runs all three first): the app is pointed at SERVICE_PORT_BASE+1..10, the stack's
# ports, unless a CW_WEB_<SERVICE>_URL is already in the environment, and given the rulebook
# tokens make web-stack gave the rulebook (CW_RULEBOOK_*_TOKEN from .env, else the placeholders),
# unless CW_WEB_RULEBOOK_*_TOKEN is already set; playwright.config.ts turns web.publish_actions
# on for the run. Without the stack and the seed, the specs that need them are skipped locally
# (and fail on CI). BILLING names the billing provider the stack was started with (none unless
# make web-stack had BILLING=memory).
web-e2e: check-pnpm ## Build the web app and run Playwright with axe against next start on WEB_PORT and the web-stack services (after make web-stack-wait and make web-seed)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	base=$${SERVICE_PORT_BASE:-8000}; i=0; \
	for svc in $(SERVICES); do \
	  i=$$((i+1)); var=CW_WEB_$$(echo "$$svc" | tr 'a-z-' 'A-Z_')_URL; \
	  eval "[ -n \"\$${$$var:-}\" ] || export $$var=http://localhost:$$((base+i))"; \
	done; \
	export CW_WEB_RULEBOOK_WRITE_TOKEN="$${CW_WEB_RULEBOOK_WRITE_TOKEN:-$${CW_RULEBOOK_WRITE_TOKEN:-local-write-token}}"; \
	export CW_WEB_RULEBOOK_REVIEW_TOKEN="$${CW_WEB_RULEBOOK_REVIEW_TOKEN:-$${CW_RULEBOOK_REVIEW_TOKEN:-local-review-token}}"; \
	$(PNPM) --filter web build && \
	PORT=$${WEB_PORT:-3000} CW_WEB_ENV=test WEB_STACK_BILLING=$(BILLING) $(PNPM) --filter web e2e --project=chromium

web-screens: check-pnpm ## Regenerate docs/web/screens.md from the screen registry
	$(PNPM) --filter web screens:gen

web-screens-check: check-pnpm ## docs/web/screens.md matches the screen registry (part of make check)
	$(PNPM) --filter web screens:check

openapi-ts: check-pnpm ## Generate TypeScript types from packages/contracts/openapi into clients/typescript/openapi
	$(PNPM) --filter @compliancewatch/contracts openapi-ts

openapi-ts-check: check-pnpm ## The generated OpenAPI types match the committed specs (part of make check)
	$(PNPM) --filter @compliancewatch/contracts openapi-ts:check

# ---- Product ---------------------------------------------------------------------------------
.PHONY: product product-role product-start product-wait product-seed product-check product-e2e product-down product-logs
# The local product (ADR-013 on the dev stack, docs/onboarding/product.md): the one deployable's
# app and worker processes (composition/mvp) with Kafka and Temporal on, and next dev for the web
# app. make product-seed fills it with synthetic tenants and the demo publication, and
# make product-check proves that a published rule becomes decisions, obligations with citations
# and a change card sent through the notification sink (cw-product, tools/demo cw_demo.product).
# make web-stack stays the UI-only stack: ten separate services and no worker, so nothing there
# turns a decision into obligations or a message. Both use make dev's Postgres, Kafka and
# Temporal, and the product's worker relays and consumes whatever either stack writes there.
#
# The services connect as PRODUCT_DB_USER (cw_app), a role that owns nothing and is not a
# superuser, so row-level security keeps the tenants apart as it does in a deployment; make
# product-role creates it on the running Postgres (infra/dev/postgres/50-app-role.sql), safe to
# repeat. make migrate, make run and make web-stack still connect as the superuser.
#
# The product's own settings are passed here and nowhere else, never as a registry or settings
# default: header auth; both listeners on 127.0.0.1; the worker's health on PRODUCT_WORKER_PORT
# (8081, since 8001 is identity's under make run and make web-stack); the worker's Kafka and
# Temporal switches, the reminder sweep and the rolling window on; the engine's recompute on
# profile.updated on, with the rulebook's in-force listing cached for five seconds, and its
# fan-out of rule.published on (CW_APPLICABILITY_FANOUT_ENABLED); obligation's consumer of the rule
# events on (CW_OBLIGATION_RULE_EVENTS_ENABLED); a CA firm's bulk change card on
# (CW_NOTIFICATION_BULK_ENABLED); rule publishing on with the placeholder
# tokens local-write-token and local-review-token (not secrets; values in .env win); the profile's
# static GSTIN lookup, so the demo GSTIN pre-fills; the notification sink in place of the real
# channels, recording into var/product/sink.jsonl, with a five-second batching window so a change
# card goes within the check's wait; and message links to the product's web app. The web app gets
# every CW_WEB_*_URL at the internal listener and builds into .next/product, so it runs beside a
# make web-dev of the same checkout (Next allows one dev server per build directory). Pids and
# logs are under var/product; make product-down stops only the processes whose pids it recorded,
# with their children.
PRODUCT_DIR := var/product
PRODUCT_DB_USER ?= cw_app
PRODUCT_DB_PASSWORD ?= cw_app
PRODUCT_WORKER_PORT ?= 8081
PRODUCT_WAIT_SECONDS ?= 120
WEB ?= 1
PROC ?= app
FOLLOW ?= 1
PRODUCT_ENV = CW_AUTH_MODE=header CW_MVP_HOST=127.0.0.1 \
  CW_DATABASE_URL="postgresql+psycopg://$(PRODUCT_DB_USER):$(PRODUCT_DB_PASSWORD)@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}" \
  CW_MVP_WORKER_HEALTH_PORT=$(PRODUCT_WORKER_PORT) \
  CW_WORKER_KAFKA_ENABLED=true CW_WORKER_TEMPORAL_ENABLED=true CW_OBLIGATION_SWEEP_ENABLED=true \
  CW_APPLICABILITY_RECOMPUTE_ENABLED=true CW_APPLICABILITY_ENGINE_RULES_CACHE_SECONDS=5 \
  CW_APPLICABILITY_FANOUT_ENABLED=true CW_OBLIGATION_RULE_EVENTS_ENABLED=true \
  CW_NOTIFICATION_BULK_ENABLED=true CW_RULEBOOK_PUBLISH_ENABLED=true \
  CW_RULEBOOK_WRITE_TOKEN="$${CW_RULEBOOK_WRITE_TOKEN:-local-write-token}" \
  CW_RULEBOOK_REVIEW_TOKEN="$${CW_RULEBOOK_REVIEW_TOKEN:-local-review-token}" \
  CW_PROFILE_GSTIN_LOOKUP=static CW_NOTIFICATION_CHANNELS=sink \
  CW_NOTIFICATION_SINK_PATH=$(PRODUCT_DIR)/sink.jsonl CW_NOTIFICATION_BATCH_WINDOW_SECONDS=5 \
  CW_WEB_BASE_URL="http://localhost:$${WEB_PORT:-3000}"

product: check-uv ## The local product: make dev, make migrate, the seed calendar, cw-mvp serve and worker (Kafka, Temporal on), next dev on WEB_PORT (3000): make product [WEB=0] [WEB_PORT=3400]
	@$(MAKE) --no-print-directory dev
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory product-role
	@$(MAKE) --no-print-directory seed SERVICE=rulebook
	@$(MAKE) --no-print-directory product-start
	@$(MAKE) --no-print-directory product-wait

product-role: check-docker ## Create or refresh PRODUCT_DB_USER, the product's role under row-level security, on the running Postgres (after make migrate)
	$(COMPOSE) exec -T postgres sh -c 'psql -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v app_user=$(PRODUCT_DB_USER) -v app_password=$(PRODUCT_DB_PASSWORD)' < infra/dev/postgres/50-app-role.sql
	@echo "role $(PRODUCT_DB_USER) can use every service schema; row-level security applies to it"

product-start: check-uv
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	[ "$(WEB)" = "0" ] || [ "$(WEB)" = "1" ] || { echo "usage: make product [WEB=0|1] [WEB_PORT=3000]"; exit 1; }; \
	mkdir -p $(PRODUCT_DIR); \
	public_port=$${CW_MVP_PUBLIC_PORT:-8000}; internal_port=$${CW_MVP_INTERNAL_PORT:-8080}; web_port=$${WEB_PORT:-3000}; \
	running() { [ -f "$(PRODUCT_DIR)/$$1.pid" ] && kill -0 "$$(cat "$(PRODUCT_DIR)/$$1.pid")" 2>/dev/null; }; \
	taken() { for port in "$$@"; do if (exec 3<>"/dev/tcp/127.0.0.1/$$port") 2>/dev/null; then echo "$$port"; return 0; fi; done; return 1; }; \
	start() { proc=$$1; ports=$$2; shift 2; \
	  if running "$$proc"; then echo "  $$proc already running (pid $$(cat "$(PRODUCT_DIR)/$$proc.pid"))"; return 0; fi; \
	  if busy=$$(taken $$ports); then echo "error: port $$busy is in use, so the product's $$proc cannot start; free it, or see docs/onboarding/product.md"; return 1; fi; \
	  nohup "$$@" > "$(PRODUCT_DIR)/$$proc.log" 2>&1 & echo $$! > "$(PRODUCT_DIR)/$$proc.pid"; \
	  echo "  $$proc started (pid $$(cat "$(PRODUCT_DIR)/$$proc.pid"), log $(PRODUCT_DIR)/$$proc.log)"; }; \
	echo "product: cw-mvp serve on $$public_port and $$internal_port, cw-mvp worker (health on $(PRODUCT_WORKER_PORT))"; \
	start app "$$public_port $$internal_port" env $(PRODUCT_ENV) $(UV) run --package compliancewatch-mvp cw-mvp serve || exit 1; \
	start worker "$(PRODUCT_WORKER_PORT)" env $(PRODUCT_ENV) $(UV) run --package compliancewatch-mvp cw-mvp worker || exit 1; \
	if [ "$(WEB)" = "1" ]; then \
	  for svc in $(SERVICES); do export "CW_WEB_$$(echo "$$svc" | tr 'a-z-' 'A-Z_')_URL=http://localhost:$$internal_port"; done; \
	  if [ -z "$${CW_WEB_AUTH_PROVIDER:-}" ] && ! grep -qs '^CW_WEB_AUTH_PROVIDER=.' apps/web/.env.local; then export CW_WEB_AUTH_PROVIDER=fake; fi; \
	  if [ -z "$${CW_WEB_SESSION_SECRET:-}" ] && ! grep -qs '^CW_WEB_SESSION_SECRET=.' apps/web/.env.local; then \
	    export CW_WEB_SESSION_SECRET="$$(openssl rand -base64 32)"; echo "  web: no session secret in apps/web/.env.local, so one for this run"; fi; \
	  export PORT=$$web_port WEB_DIST_DIR=.next/product; \
	  start web "$$web_port" $(PNPM) --filter web dev || exit 1; \
	fi

product-wait: ## Wait for the product: the internal listener ready, the worker healthy and the web app answering (PRODUCT_WAIT_SECONDS, default 120)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	deadline=$$((SECONDS + $(PRODUCT_WAIT_SECONDS))); status=0; \
	public="http://127.0.0.1:$${CW_MVP_PUBLIC_PORT:-8000}"; internal="http://127.0.0.1:$${CW_MVP_INTERNAL_PORT:-8080}"; \
	worker="http://127.0.0.1:$(PRODUCT_WORKER_PORT)"; web="http://localhost:$${WEB_PORT:-3000}"; \
	wait_for() { proc=$$1; url=$$2; \
	  until curl -sf "$$url" >/dev/null 2>&1; do \
	    if [ -f "$(PRODUCT_DIR)/$$proc.pid" ] && ! kill -0 "$$(cat "$(PRODUCT_DIR)/$$proc.pid")" 2>/dev/null; then \
	      echo "error: the product's $$proc exited; the end of $(PRODUCT_DIR)/$$proc.log:"; tail -n 20 "$(PRODUCT_DIR)/$$proc.log"; return 1; fi; \
	    if [ $$SECONDS -ge $$deadline ]; then echo "error: the product's $$proc did not answer $$url (see $(PRODUCT_DIR)/$$proc.log)"; return 1; fi; \
	    sleep 1; \
	  done; echo "  $$proc ready: $$url"; }; \
	wait_for app "$$internal/ready" || status=1; \
	wait_for worker "$$worker/health" || status=1; \
	if [ "$(WEB)" = "1" ]; then wait_for web "$$web/api/health" || status=1; fi; \
	if [ $$status -eq 0 ]; then \
	  echo ""; echo "ComplianceWatch product"; \
	  echo "  public listener    $$public   (the edge's routes; /health, /ready)"; \
	  echo "  internal listener  $$internal   (every route; the web app and cw-product call it)"; \
	  echo "  worker health      $$worker/health   (/loops lists consumers, relays, jobs, task queues)"; \
	  if [ "$(WEB)" = "1" ]; then echo "  web app            $$web   (development sign-in after make product-seed)"; fi; \
	  echo "  sink               $(PRODUCT_DIR)/sink.jsonl   (every message the product would have sent)"; \
	  echo "Next: make product-seed, then make product-check"; \
	fi; \
	exit $$status

product-seed: check-uv ## Fill the running product: synthetic tenants, the demo publication, first decisions (cw-product seed): make product-seed [ARGS="--rule gstr9_annual --json"]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	$(PRODUCT_ENV) CW_LOG_LEVEL=WARNING $(UV) run --package compliancewatch-demo cw-product seed $(ARGS)

# The fanout step reads the business directory and the audit rows of no tenant, which no route
# serves and no policy lets cw_app read, at CW_PRODUCT_RECORDS_URL: the database owner's URL, on a
# session cw-product opens read only (default_transaction_read_only), so it can only query. The
# rollback step withdraws gstr9_annual, so it runs only with ARGS="--destructive", which the CI
# dev-stack job passes on its fresh database; never pass it against a database you keep.
product-check: check-uv ## Prove the running product works, step by step (cw-product check; exit 0 means accepted): make product-check [ARGS="--step loop --json"] [ARGS="--destructive"] (CI only)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	$(PRODUCT_ENV) CW_LOG_LEVEL=WARNING \
	  CW_PRODUCT_RECORDS_URL="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}" \
	  $(UV) run --package compliancewatch-demo cw-product check $(ARGS)

# The web app's real-data journeys (Playwright project product, apps/web/e2e/product): the web app
# is built into its own directory (.next/e2e-product, so neither the default build nor the
# .next/product of make product's next dev is touched) and started with next start on
# PRODUCT_E2E_PORT, every CW_WEB_*_URL at the product's internal listener (CW_E2E_PRODUCT_URL), the
# fake sign-in and CW_WEB_ENV=test; it signs in as the tenant make product-seed recorded. It
# writes as that tenant: a probe business of its own, started, completed and commented on. The
# oversight journey sets and releases the global fan-out hold, runs a dry run of the annual return
# and, as the synthetic CA firm, sends its change card to a client contact made for the run and
# removed afterwards; it withdraws nothing (make product-check --destructive proves the rollback).
PRODUCT_E2E_PORT ?= 3400

product-e2e: check-pnpm ## Build the web app and run the Playwright product project against the running product (after make product and make product-seed): make product-e2e [PRODUCT_E2E_PORT=3400]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	export WEB_DIST_DIR=.next/e2e-product; \
	$(PNPM) --filter web build && \
	PORT=$(PRODUCT_E2E_PORT) CW_WEB_ENV=test CW_E2E_PRODUCT_URL="http://127.0.0.1:$${CW_MVP_INTERNAL_PORT:-8080}" \
	  $(PNPM) --filter web e2e --project=product

product-down: ## Stop the product's processes: only the pids make product recorded in var/product, with their children (logs stay)
	@tree() { for child in $$(pgrep -P "$$1" 2>/dev/null); do tree "$$child"; done; echo "$$1"; }; \
	for proc in web worker app; do \
	  pidfile=$(PRODUCT_DIR)/$$proc.pid; [ -f "$$pidfile" ] || continue; pid=$$(cat "$$pidfile"); \
	  if ! kill -0 "$$pid" 2>/dev/null; then echo "  $$proc was not running"; rm -f "$$pidfile"; continue; fi; \
	  case "$$(ps -o command= -p "$$pid")" in \
	    *cw-mvp*|*"--filter web dev"*) ;; \
	    *) echo "  $$proc: pid $$pid now belongs to another program; left alone"; rm -f "$$pidfile"; continue ;; \
	  esac; \
	  pids=$$(tree "$$pid"); kill -TERM $$pids 2>/dev/null; \
	  n=0; while kill -0 "$$pid" 2>/dev/null && [ $$n -lt 40 ]; do n=$$((n+1)); sleep 0.25; done; \
	  for left in $$pids; do kill -0 "$$left" 2>/dev/null && kill -KILL "$$left" 2>/dev/null; done; \
	  echo "  $$proc stopped (pid $$pid)"; rm -f "$$pidfile"; \
	done; true

product-logs: ## Show a product process's log: make product-logs PROC=app|worker|web [FOLLOW=0]
	@case "$(PROC)" in app|worker|web) ;; *) echo "usage: make product-logs PROC=app|worker|web [FOLLOW=0]"; exit 1 ;; esac; \
	log=$(PRODUCT_DIR)/$(PROC).log; [ -f "$$log" ] || { echo "no $$log: make product starts the $(PROC) process"; exit 1; }; \
	if [ "$(FOLLOW)" = "0" ]; then tail -n 200 "$$log"; else tail -n 100 -f "$$log"; fi

# ---- The product from its image (ADR-013's one deployable as it ships) ------------------------
.PHONY: mvp-image product-image product-image-down product-image-logs
# make product-image runs the product from composition/mvp/Dockerfile's image on the dev stack, in
# the compose profile mvp (docker-compose.yml): mvp-release runs cw-mvp release (every service's
# migrations as the database owner, then the topics of composition/mvp/topics.toml), and once it
# has, mvp-app runs cw-mvp serve on 8000 and 8080 and mvp-worker cw-mvp worker with its health on
# PRODUCT_WORKER_PORT, with the settings make product passes its processes (x-mvp-env). The image
# is built first unless MVP_BUILD=0 (CI builds it with buildx and its cache). cw_app is created
# before the release (make product-role: its default privileges cover the tables the release
# makes), and the seed calendar is loaded with the image's rulebook-seed afterwards. make
# product-seed and make product-check then run against it unchanged: the same ports, cw_app, and
# the sink in var/product, which the containers write as you (CW_MVP_USER is your uid and gid).
# It uses make product's ports, so one of the two runs at a time. make product-image-down removes
# the three containers and nothing else.
MVP_IMAGE ?= compliancewatch-mvp:local
MVP_BUILD ?= 1
MVP_COMPOSE = CW_MVP_IMAGE=$(MVP_IMAGE) CW_MVP_USER="$$(id -u):$$(id -g)" \
  PRODUCT_DB_USER=$(PRODUCT_DB_USER) PRODUCT_DB_PASSWORD=$(PRODUCT_DB_PASSWORD) \
  PRODUCT_WORKER_PORT=$(PRODUCT_WORKER_PORT) $(COMPOSE) --profile mvp
# dev-down and dev-reset remove the deployable's containers too.
PROFILES += --profile mvp

mvp-image: check-docker ## Build the one deployable's image (composition/mvp/Dockerfile) as MVP_IMAGE (compliancewatch-mvp:local)
	docker build -f composition/mvp/Dockerfile -t $(MVP_IMAGE) .

product-image: check-docker ## The local product from the image: make dev, the image, cw_app, cw-mvp release, serve and worker in containers, the seed calendar: make product-image [MVP_BUILD=0]
	@for proc in app worker web; do pidfile=$(PRODUCT_DIR)/$$proc.pid; \
	  if [ -f "$$pidfile" ] && kill -0 "$$(cat "$$pidfile")" 2>/dev/null; then \
	    echo "error: make product's $$proc is running (pid $$(cat "$$pidfile")); make product-down first"; exit 1; fi; \
	done
	@$(MAKE) --no-print-directory dev
	@if [ "$(MVP_BUILD)" != "0" ]; then $(MAKE) --no-print-directory mvp-image; fi
	@$(MAKE) --no-print-directory product-role
	@mkdir -p $(PRODUCT_DIR)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	echo "product-image: cw-mvp release, then cw-mvp serve and worker from $(MVP_IMAGE)"; \
	$(MVP_COMPOSE) up -d --wait --wait-timeout $(PRODUCT_WAIT_SECONDS) mvp-app mvp-worker || { \
	  $(MVP_COMPOSE) logs --no-color --tail 40 mvp-release mvp-app mvp-worker; exit 1; }; \
	$(MVP_COMPOSE) logs --no-color --no-log-prefix mvp-release; \
	echo "product-image: the seed calendar's drafts (rulebook-seed in the image)"; \
	$(MVP_COMPOSE) run --rm --no-deps -e CW_DB_SCHEMA=rulebook -e CW_LOG_LEVEL=WARNING \
	  -e CW_DATABASE_URL="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@postgres:5432/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3Drulebook%2Cpublic" \
	  mvp-release rulebook-seed || exit 1; \
	echo ""; echo "ComplianceWatch product from the image $(MVP_IMAGE)"; \
	echo "  public listener    http://127.0.0.1:$${CW_MVP_PUBLIC_PORT:-8000}   (the edge's routes; /health, /ready)"; \
	echo "  internal listener  http://127.0.0.1:$${CW_MVP_INTERNAL_PORT:-8080}   (every route; cw-product calls it)"; \
	echo "  worker health      http://127.0.0.1:$(PRODUCT_WORKER_PORT)/health   (/loops lists consumers, relays, jobs, task queues)"; \
	echo "  sink               $(PRODUCT_DIR)/sink.jsonl"; \
	echo "Next: make product-seed, then make product-check; make product-image-down stops it"

product-image-down: check-docker ## Remove the image product's containers (mvp-release, mvp-app, mvp-worker); the dev stack keeps running
	$(MVP_COMPOSE) rm --stop --force mvp-worker mvp-app mvp-release

product-image-logs: check-docker ## Show a container's log of the image product: make product-image-logs PROC=app|worker|release [FOLLOW=0]
	@case "$(PROC)" in app|worker|release) ;; *) echo "usage: make product-image-logs PROC=app|worker|release [FOLLOW=0]"; exit 1 ;; esac; \
	if [ "$(FOLLOW)" = "0" ]; then $(MVP_COMPOSE) logs --no-color --tail 200 mvp-$(PROC); \
	else $(MVP_COMPOSE) logs --follow --tail 100 mvp-$(PROC); fi

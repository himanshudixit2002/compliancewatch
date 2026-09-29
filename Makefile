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
PY_DIRS := $(addprefix packages/,$(PY_PACKAGES)) packages/contracts/clients/python $(addprefix services/,$(SERVICES)) evals/harness tools/demo

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

run: check-uv ## Run one service with reload: make run SERVICE=identity [PORT=8001]
	@[ -n "$(SERVICE)" ] || { echo "usage: make run SERVICE=<identity|profile|...> [PORT=8000]"; exit 1; }
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	url="postgresql+psycopg://$${POSTGRES_USER:-cw}:$${POSTGRES_PASSWORD:-cw}@localhost:$${POSTGRES_PORT:-5432}/$${POSTGRES_DB:-compliancewatch}?options=-csearch_path%3D$(SCHEMA)%2Cpublic"; \
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" \
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
	CW_DATABASE_URL="$$url" CW_DB_SCHEMA="$(SCHEMA)" \
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
.PHONY: web-dev web-stack web-stack-wait web-stack-down web-stack-logs web-seed web-e2e-install web-e2e web-screens web-screens-check openapi-ts openapi-ts-check
CHECKS += web-screens-check openapi-ts-check
# The port comes from WEB_PORT in .env (3000 unless the file says otherwise); a value already in
# the environment wins, as for every variable the recipes source.

web-dev: check-pnpm ## next dev on WEB_PORT from .env; /admin lists the internal tools, /design the UI kit
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	PORT=$${WEB_PORT:-3000} $(PNPM) --filter web dev

# The services behind the web app, every one on SERVICE_PORT_BASE+1 .. +10 in the SERVICES order
# (8001-8010 unless .env moves the base; a second clone sets 9200), started with nohup, pids and
# logs under var/web-stack. The stack is defined here rather than inherited from .env so a fresh
# clone and CI see the same states: memory stores (no container), the profile's built-in static
# GSTIN lookup (the demo GSTIN pre-fills), the billing provider "none" (subscribe answers 503),
# the publish flow and the KAG layer off, the inter-service URLs on the same base, and the
# rulebook write token from .env or the placeholder local-write-token (not a secret). Memory
# stores lose their rows when the stack stops; STORE=postgres runs every store on the compose
# Postgres instead (make dev and make migrate first), with the schema search path make run uses.
WEB_STACK_DIR := var/web-stack
WEB_STACK_WAIT_SECONDS ?= 60
STORE ?= memory

web-stack: check-uv ## Start every service on SERVICE_PORT_BASE+1..10 with memory stores (pids and logs in var/web-stack): make web-stack [STORE=postgres]
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	[ "$(STORE)" = "memory" ] || [ "$(STORE)" = "postgres" ] || { echo "usage: make web-stack [STORE=memory|postgres]"; exit 1; }; \
	mkdir -p $(WEB_STACK_DIR); base=$${SERVICE_PORT_BASE:-8000}; i=0; \
	token="$${CW_RULEBOOK_WRITE_TOKEN:-local-write-token}"; \
	echo "web stack: services on $$((base+1))-$$((base+10)), $(STORE) stores"; \
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
	  CW_IDENTITY_STORE=$(STORE) CW_PROFILE_STORE=$(STORE) CW_RULEBOOK_STORE=$(STORE) CW_OBLIGATION_STORE=$(STORE) CW_LLM_LEDGER=$(STORE) \
	  CW_PROFILE_GSTIN_LOOKUP=static CW_BILLING_PROVIDER=none CW_RULEBOOK_PUBLISH_ENABLED=false CW_QA_KAG_ENABLED=false \
	  CW_RULEBOOK_WRITE_TOKEN="$$token" \
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

# No page on main calls a service, so the suite runs without the stack; the seeded-tenant sign-in
# test is skipped until make web-stack, web-stack-wait and web-seed have run (CI runs all three).
web-e2e: check-pnpm ## Build the web app and run Playwright with axe against next start on WEB_PORT (after make web-seed for the seeded-tenant test)
	@env0=$$(export -p); set -a; [ -f .env ] && . ./.env; set +a; eval "$$env0"; \
	$(PNPM) --filter web build && \
	PORT=$${WEB_PORT:-3000} CW_WEB_ENV=test $(PNPM) --filter web e2e

web-screens: check-pnpm ## Regenerate docs/web/screens.md from the screen registry
	$(PNPM) --filter web screens:gen

web-screens-check: check-pnpm ## docs/web/screens.md matches the screen registry (part of make check)
	$(PNPM) --filter web screens:check

openapi-ts: check-pnpm ## Generate TypeScript types from packages/contracts/openapi into clients/typescript/openapi
	$(PNPM) --filter @compliancewatch/contracts openapi-ts

openapi-ts-check: check-pnpm ## The generated OpenAPI types match the committed specs (part of make check)
	$(PNPM) --filter @compliancewatch/contracts openapi-ts:check

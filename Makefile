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
PY_DIRS := $(addprefix packages/,$(PY_PACKAGES)) packages/contracts/clients/python $(addprefix services/,$(SERVICES))

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

dev-observability: check-docker ## Same as dev plus Langfuse (compose profile: observability)
	@[ -f .env ] || { cp .env.example .env && echo "created .env from .env.example"; }
	$(COMPOSE) --profile observability up -d --wait --wait-timeout 240
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

py-typecheck: check-uv ## mypy --strict per package (src, tests, migrations/env.py) and the root conftest
	@status=0; \
	for d in $(PY_DIRS); do \
	  targets="$$d/src"; \
	  [ -d "$$d/tests" ] && targets="$$targets $$d/tests"; \
	  [ -f "$$d/migrations/env.py" ] && targets="$$targets $$d/migrations/env.py"; \
	  echo "mypy $$targets"; \
	  $(UV) run mypy $$targets || status=1; \
	done; \
	$(UV) run mypy conftest.py packages/contracts/scripts || status=1; \
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
.PHONY: install lint format typecheck test check eval migrate run worker relay openapi contracts contracts-check hooks ci-lint
install: py-sync ts-install ## Install both toolchains

lint: py-lint ts-lint ## Lint both sides (CI step 1)

format: py-format ts-format ## Auto-format both sides

typecheck: py-typecheck ts-typecheck ## mypy --strict and tsc --strict (CI step 1)

test: py-test ts-test ## Unit and contract tests on both sides (CI step 2)

check: lint typecheck test importlint lock-check contracts-check ## Everything CI runs before integration tests

eval: ## Eval harness against evals/golden (not built yet; prints a notice)
	@echo "make eval: the eval harness under evals/harness is not built yet; nothing to run."

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

worker: check-uv ## Run a service's Temporal worker: make worker SERVICE=pipeline
	@[ -n "$(SERVICE)" ] || { echo "usage: make worker SERVICE=<pipeline|...>"; exit 1; }
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

contracts: check-uv check-pnpm ## Generate the event clients (pydantic + TypeScript) from packages/contracts/events/schemas
	$(UV) run python packages/contracts/scripts/generate_events.py

contracts-check: check-uv check-pnpm ## Event schemas pass the 2020-12 metaschema and the generated clients match them
	$(UV) run check-jsonschema --check-metaschema packages/contracts/events/schemas/*.json
	@$(MAKE) --no-print-directory contracts
	@drift=$$(git status --porcelain -- packages/contracts/clients/python/src/cw_contracts/events packages/contracts/clients/typescript/events); \
	if [ -n "$$drift" ]; then echo "$$drift"; echo "error: generated event clients are out of date; commit the output of make contracts"; exit 1; fi
	@echo "event contracts OK"

hooks: ## Install the pre-commit and commit-msg hooks
	pre-commit install --install-hooks

ci-lint: ## Validate GitHub Actions workflows and the pre-commit config without running them
	actionlint -color
	pre-commit validate-config

# Local development

Everything runs from the repo root through `make`; `make help` lists every target.

## Prerequisites

| Tool | Install | Notes |
| --- | --- | --- |
| Docker | Docker Desktop, or `brew install colima docker docker-compose docker-buildx` then `colima start --cpu 4 --memory 8 --disk 60` | Homebrew's `docker-compose` and `docker-buildx` are CLI plugins (`docker build` needs buildx for the `--mount=type=cache` instructions in the Dockerfiles): `~/.docker/config.json` needs `{"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}` (brew prints this). The default 2 GB Colima VM is too small for Redpanda + Temporal + Postgres. |
| uv | `brew install uv` | `uv sync` downloads a managed CPython 3.12 (`.python-version`); the Homebrew `python3` is never used. |
| pnpm + Node 22.18+ | `brew install pnpm node` | `package.json` pins `pnpm@11.15.0`; pnpm switches itself to that version. |
| pre-commit (optional but expected) | `brew install pre-commit` or `uv tool install pre-commit`, then `make hooks` | Installs the pre-commit and commit-msg hooks (ruff, prettier, gitleaks, conventional commits). |
| actionlint, gitleaks (optional) | `brew install actionlint gitleaks` | `make ci-lint` validates the workflows locally. |

GNU make 3.81 (the macOS default) is enough.

## First run

```bash
cp .env.example .env
make install                 # uv sync --all-packages; pnpm install --frozen-lockfile
make dev                     # pulls ~2 GB of images the first time; waits until every container is healthy
make migrate                 # alembic upgrade head for all ten services
make run SERVICE=identity    # http://localhost:8001/health
make test
```

## Ports and URLs

| What | Host | Notes |
| --- | --- | --- |
| Postgres 16 + pgvector | `localhost:5432`, user/password/db `cw`/`cw`/`compliancewatch` | one schema per service plus `audit`; `make dev-psql` |
| Redis 7 | `localhost:6379` | |
| Kafka API (Redpanda) | `localhost:19092` | containers use `redpanda:9092`; schema registry `http://localhost:18081`; admin `localhost:19644`; topics are auto-created, dead letters go to `<topic>.dlq` |
| Temporal | `localhost:7233` | UI `http://localhost:8233` |
| Langfuse (profile `observability`) | `http://localhost:3010` | `make dev-observability`; login `dev@compliancewatch.local` / `dev-password`, keys `pk-lf-dev` / `sk-lf-dev` |
| OpenTelemetry collector (profile `observability`) | `localhost:4317` gRPC, `4318` HTTP, health `http://localhost:13133` | set `CW_OTEL_ENDPOINT=http://localhost:4317` in `.env` to export traces and metrics |
| Prometheus (profile `observability`) | `http://localhost:9090` | scrapes the collector; 2 days of retention |
| Grafana (profile `observability`) | `http://localhost:3030` | anonymous admin; dashboard "ComplianceWatch services", Explore for Tempo traces |
| Fake LLM gateway (profile `llm`) | `http://localhost:8090` | `make dev-llm`; the `services/llm-gateway` image with the fake provider and an in-memory ledger, no key |
| Services (`make run`) | `localhost:8001` .. `8010` | identity, profile, rulebook, applicability-engine, obligation, notification, qa, llm-gateway, eval, pipeline; containers listen on 8000 |
| Web app | `http://localhost:3000` | `pnpm --filter web dev`; `/admin` for the internal tools |
| WhatsApp bot | `http://localhost:8080` | `pnpm --filter whatsapp-bot dev`; `/health`, `GET/POST /webhook` |

Every host port is a variable in `.env` (`POSTGRES_PORT`, `REDIS_PORT`, `REDPANDA_KAFKA_PORT`, `REDPANDA_SCHEMA_REGISTRY_PORT`, `REDPANDA_ADMIN_PORT`, `TEMPORAL_PORT`, `TEMPORAL_UI_PORT`, `LANGFUSE_PORT`, `OTEL_GRPC_PORT`, `OTEL_HTTP_PORT`, `OTEL_HEALTH_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`, `FAKE_LLM_PORT`). Other projects on this machine use 5432, 6379, 9092, 8080 and 3000 when they run; change the port in `.env`, not in `docker-compose.yml`.

## Running one service

`make run SERVICE=<dir> [PORT=<n>]` starts uvicorn with reload on the service's dev port and exports `CW_DATABASE_URL` (with `search_path=<schema>,public`) and `CW_DB_SCHEMA` for it. Settings come from `py_common.settings.Settings`: `CW_*` variables, then `.env`, then defaults. Empty values count as unset. `make run` and `make migrate` source `.env` the same way: a variable already in the environment wins over the file, so `CW_LLM_LEDGER=postgres make run SERVICE=llm-gateway` does what it says.

`make relay SERVICE=<dir>` runs the outbox relay for that service's schema with the same
environment: it publishes the service's `outbox_event` rows to Redpanda and dead-letters to
`<topic>.dlq` (`docs/runbooks/outbox-relay.md`). No service has the `outbox_event` table yet, so
the relay logs `outbox.table_missing` and exits until the first producing service's migration
creates it. `docker compose exec redpanda rpk topic list`
shows the topics; `rpk topic consume <topic> -n 1` reads a message.

`make worker SERVICE=pipeline` runs the service's Temporal worker with the same environment;
`services/pipeline/README.md` shows how to start the sample workflow and
`docs/runbooks/temporal-worker.md` what to do when a run fails.

## Seed calendar

`make migrate SERVICE=rulebook` then `make seed SERVICE=rulebook` loads the thirteen standing
GST obligations from `services/rulebook/seed/gst_calendar.yaml` as draft rule versions
(`select rule_key, version, status, seed_status from rulebook.rule_version join rulebook.rule
on rule.id = rule_id` through `make dev-psql`). `ARGS=--check` validates the file without
writing. Every version stays `needs_review` until an analyst reviews it.

## Row-level security in the dev stack

Tenant tables (the obligation service's first) carry a policy on `tenant_id`, but the dev
stack connects as `cw`, the container's superuser, and a superuser bypasses every policy. The
policy is therefore visible but not enforced locally; the obligation integration test proves it
through a plain role. A non-superuser application role for the dev stack arrives with the
deployment work, where every service gets its own role.

## Traces and metrics

`make dev-observability` adds the OpenTelemetry collector, Prometheus, Tempo and Grafana to
the stack. Put `CW_OTEL_ENDPOINT=http://localhost:4317` in `.env` (or prefix one command with
it), run a service or a worker, and open http://localhost:3030: the "ComplianceWatch services"
dashboard shows request rate, p95 latency and errors per service and the outbox relay counters;
Explore with the Tempo datasource finds traces by `service.name`. Log lines inside a request or
an activity carry `trace_id`. A changed `infra/dev/otel/collector.yaml` needs
`docker compose up -d --force-recreate otel-collector`.

## LLM gateway

`services/llm-gateway` is the only service that calls a language model, and it needs nothing from the stack to start: `make run SERVICE=llm-gateway` serves every route from the deterministic fake provider with an in-memory cost ledger on `http://localhost:8008`. The same thing as a container is `make dev-llm` (compose profile `llm`, port `8090`); other services and CI call that when no real model is wanted.

```bash
curl -s -X POST http://localhost:8008/v1/llm-gateway/completions \
  -H 'content-type: application/json' \
  -d '{"feature":"smoke","prompt":"smoke.echo@1","user":"hello"}'
```

- **Persist the ledger.** `make dev && make migrate SERVICE=llm-gateway`, then `CW_LLM_LEDGER=postgres make run SERVICE=llm-gateway`; rows land in `llm_gateway.cost_ledger` (`make dev-psql`).
- **Real models.** Put a Vercel AI Gateway key in `.env` as `CW_AI_GATEWAY_API_KEY` and set `CW_LLM_PROVIDER=vercel`. The key stays in `.env` (git-ignored); the `fake-llm` container never gets one. Override a route with `CW_LLM_ROUTES__<FEATURE>=primary[,fallback]`; naming one model drops the fallback.
- **Traces.** `make dev-observability`, then in `.env`: `CW_LANGFUSE_HOST=http://localhost:3010`, `CW_LANGFUSE_PUBLIC_KEY=pk-lf-dev`, `CW_LANGFUSE_SECRET_KEY=sk-lf-dev`. Every call shows up as a trace at http://localhost:3010.
- **API change.** `make openapi SERVICE=llm-gateway` rewrites `packages/contracts/openapi/llm-gateway.v1.json`; the contract test fails until the committed spec matches.

Settings, routes, budgets and errors: [services/llm-gateway/README.md](../../services/llm-gateway/README.md).

## Migrations

`make migrate` (all services) or `make migrate SERVICE=<dir>`. Each service owns one schema and its own `alembic_version` table inside it (`version_table_schema`), so services never see each other's tables. `pgvector` lives in `public`, which stays on every search path. Schemas are created once per volume by `infra/dev/postgres/init.sql`; clusters create them through migrations and Helm jobs instead.

## Reset

`make dev-reset` stops the stack and deletes the volumes, so `init.sql` runs again on the next `make dev`. `make dev-down` keeps the data.

## Troubleshooting

- **Kafka clients time out from the host.** Use `localhost:19092` (the advertised external listener), never `9092`. Inside containers use `redpanda:9092`.
- **Temporal restarts in a loop.** It needs the `temporal` and `temporal_visibility` databases that `init.sql` creates; if you changed `init.sql` on an existing volume, `make dev-reset`. `DB` must stay `postgres12`.
- **`docker compose` not found with Homebrew.** Add the `cliPluginsExtraDirs` entry above to `~/.docker/config.json`.
- **`error getting credentials ... docker-credential-desktop` on every pull.** A leftover `"credsStore": "desktop"` in `~/.docker/config.json` from a previous Docker Desktop install; remove that key (or point it at a helper you have installed) when using Colima.
- **Integration tests fail with `error while creating mount source path '.../.colima/default/docker.sock'`.** testcontainers' reaper mounts the Docker socket by its host path, which does not exist inside the Colima VM. `make py-test-integration` sets `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock` for this; export the same variable when calling `uv run pytest -m integration` directly.
- **`brew install docker` left no `docker` binary.** Homebrew may leave the formula unlinked when a `docker-desktop` cask is also installed: `brew link --overwrite docker`.
- **`make dev` fails with a health-check timeout.** `make dev-logs SERVICE=<postgres|redpanda|temporal>`.
- **`uv sync` says no interpreter for 3.12.** `uv python install 3.12`.
- **Apple Silicon.** Every pinned image publishes an arm64 manifest; no `platform:` overrides are needed.
- **`next dev` rewrites `apps/web/AGENTS.md` (and `CLAUDE.md`, which just points at it).** Both are maintained by Next.js and committed on purpose.

## Not in the stack yet

Seeded fixtures and the 50-document sample rulebook, Keycloak, Terraform, alert rules.

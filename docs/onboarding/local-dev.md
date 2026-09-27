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
| Kafka API (Redpanda) | `localhost:19092` | containers use `redpanda:9092`; schema registry `http://localhost:18081`; admin `localhost:19644` |
| Temporal | `localhost:7233` | UI `http://localhost:8233` |
| Langfuse (profile `observability`) | `http://localhost:3010` | `make dev-observability`; login `dev@compliancewatch.local` / `dev-password`, keys `pk-lf-dev` / `sk-lf-dev` |
| Services (`make run`) | `localhost:8001` .. `8010` | identity, profile, rulebook, applicability-engine, obligation, notification, qa, llm-gateway, eval, pipeline; containers listen on 8000 |
| Web app | `http://localhost:3000` | `pnpm --filter web dev`; `/admin` for the internal tools |
| WhatsApp bot | `http://localhost:8080` | `pnpm --filter whatsapp-bot dev`; `/health`, `GET/POST /webhook` |

Every host port is a variable in `.env` (`POSTGRES_PORT`, `REDIS_PORT`, `REDPANDA_KAFKA_PORT`, `REDPANDA_SCHEMA_REGISTRY_PORT`, `REDPANDA_ADMIN_PORT`, `TEMPORAL_PORT`, `TEMPORAL_UI_PORT`, `LANGFUSE_PORT`). Other projects on this machine use 5432, 6379, 9092, 8080 and 3000 when they run; change the port in `.env`, not in `docker-compose.yml`.

## Running one service

`make run SERVICE=<dir> [PORT=<n>]` starts uvicorn with reload on the service's dev port and exports `CW_DATABASE_URL` (with `search_path=<schema>,public`) and `CW_DB_SCHEMA` for it. Settings come from `py_common.settings.Settings`: `CW_*` variables, then `.env`, then defaults. Empty values count as unset.

## Migrations

`make migrate` (all services) or `make migrate SERVICE=<dir>`. Each service owns one schema and its own `alembic_version` table inside it (`version_table_schema`), so services never see each other's tables. `pgvector` lives in `public`, which stays on every search path. Schemas are created once per volume by `infra/dev/postgres/init.sql`; clusters create them through migrations and Helm jobs instead.

## Reset

`make dev-reset` stops the stack and deletes the volumes, so `init.sql` runs again on the next `make dev`. `make dev-down` keeps the data.

## Troubleshooting

- **Kafka clients time out from the host.** Use `localhost:19092` (the advertised external listener), never `9092`. Inside containers use `redpanda:9092`.
- **Temporal restarts in a loop.** It needs the `temporal` and `temporal_visibility` databases that `init.sql` creates; if you changed `init.sql` on an existing volume, `make dev-reset`. `DB` must stay `postgres12`.
- **`docker compose` not found with Homebrew.** Add the `cliPluginsExtraDirs` entry above to `~/.docker/config.json`.
- **`error getting credentials ... docker-credential-desktop` on every pull.** A leftover `"credsStore": "desktop"` in `~/.docker/config.json` from a previous Docker Desktop install; remove that key (or point it at a helper you have installed) when using Colima.
- **`brew install docker` left no `docker` binary.** Homebrew may leave the formula unlinked when a `docker-desktop` cask is also installed: `brew link --overwrite docker`.
- **`make dev` fails with a health-check timeout.** `make dev-logs SERVICE=<postgres|redpanda|temporal>`.
- **`uv sync` says no interpreter for 3.12.** `uv python install 3.12`.
- **Apple Silicon.** Every pinned image publishes an arm64 manifest; no `platform:` overrides are needed.
- **`next dev` rewrites `apps/web/AGENTS.md` (and `CLAUDE.md`, which just points at it).** Both are maintained by Next.js and committed on purpose.

## Not in the stack yet

Fake LLM provider container (ships with `services/llm-gateway`), OpenTelemetry collector (`CW_OTEL_ENDPOINT` stays empty), seeded fixtures and the 50-document sample rulebook (Phase 1), Keycloak, Terraform.

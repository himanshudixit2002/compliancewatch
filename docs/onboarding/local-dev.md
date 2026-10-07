# Local development

Everything runs from the repo root through `make`; `make help` lists every target. To run the
whole product (the one deployable's app and worker with Kafka and Temporal on, and the web app)
and prove its event chain, see [product.md](product.md): `make product`, `make product-seed`,
`make product-check`.

The same targets have buttons in ComplianceWatch Control, the desktop app
(`make control-panel-app` builds it on the Desktop; `make control-panel` opens the same window in
your browser): the stack, the services and their workers, the product, the data, the checks, the
pipeline's events, the flags and the checkout's processes in one window.
[control-panel.md](control-panel.md) says what each section does and what it never does.

## Prerequisites

| Tool | Install | Notes |
| --- | --- | --- |
| Docker | Docker Desktop, or `brew install colima docker docker-compose docker-buildx` then `colima start --cpu 4 --memory 8 --disk 60` | Homebrew's `docker-compose` and `docker-buildx` are CLI plugins (`docker build` needs buildx for the `--mount=type=cache` instructions in the Dockerfiles): `~/.docker/config.json` needs `{"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}` (brew prints this). The default 2 GB Colima VM is too small for Redpanda + Temporal + Postgres. |
| uv | `brew install uv` | `uv sync` downloads a managed CPython 3.12 (`.python-version`); the Homebrew `python3` is never used. |
| pnpm + Node 22.22.2+ | `brew install pnpm node` | `package.json` pins `pnpm@11.15.0`; pnpm switches itself to that version. jsdom 30, the unit tests' DOM, needs Node 22.22.2 or later on the 22 line. |
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

`make worker SERVICE=pipeline` runs the service's Temporal worker with the same environment
(after `make migrate SERVICE=pipeline`, since its ingest records what it fetches in the pipeline
schema); `services/pipeline/README.md` shows how to start an ingest and where the fetched files
go, and `docs/runbooks/temporal-worker.md` what to do when a run fails.
`make backfill SERVICE=pipeline ARGS="--source cbic_notifications --since 2026-01-01 --limit 5"`
fetches real documents from a regulator site into `var/raw/` (one request per second, honouring
`robots.txt`); `--list-only` just lists. The keys are in
`services/pipeline/src/pipeline/infrastructure/adapters/registry.py`.
`CW_PIPELINE_CRAWL_ENABLED` stays `false` locally: on, `make worker SERVICE=pipeline` crawls the
live regulator sites every time a source's cadence passes (`services/pipeline/README.md`, "The
crawl"), and `make product` and CI force it off. The source manager's routes
(`GET /v1/pipeline/sources` and the rest) work with it off; a fetch then answers 503.

`make eval` runs the eval harness in the `ci` profile (scripted answers and the in-process
gateway with the fake provider; no tokens, no network) and writes `evals/reports/latest.md`.
`make label ARGS="check"` validates the golden extraction cases; `make label ARGS="prepare ..."`
fetches documents for analysts to label (see `evals/golden/extraction/README.md`).

Flags for the pieces that need an external account, all off by default in `.env.example`:
`CW_WHATSAPP_ENABLED` (notification channel), `CW_EMAIL_ENABLED` (notification email over
SMTP), `WHATSAPP_SEND_ENABLED` (the bot's replies),
`CW_BILLING_PROVIDER` (identity billing; `memory` for a demo), `CW_PROFILE_GSTIN_LOOKUP`
(`static` for the demo table, `http` for a provider). `pnpm --filter whatsapp-bot dev` runs the
bot on 8080 against the notification service on 8006. Every flag, with its owner and removal
condition, is in `packages/flags/registry.json`; a flag without a variable of its own is set with
`CW_FLAG_<NAME>` (`packages/flags/README.md`). `make dev-flags` starts Unleash for
`CW_FLAGS_PROVIDER=unleash`.

`make demo` needs neither Docker nor accounts: it runs the demo tenant through every service in
one process and prints the transcript ([demo.md](demo.md)). `make dev-backup` and
`make dev-restore FILE=...` dump and restore the dev database.

## Profiles

`make migrate SERVICE=profile` then `make run SERVICE=profile`. In the default `header` auth mode
every call names its tenant in an `x-tenant-id` header with a UUID ("Signing in with tokens"
below uses an access token instead):

```bash
curl -s -X POST http://localhost:8002/v1/profile/registrations \
  -H 'content-type: application/json' -H 'x-tenant-id: 5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a' \
  -d '{"gstin":"29ABCDE1234F1Z5","name":"Acme Bengaluru","entity_name":"Acme"}'
```

Then `PUT /v1/profile/nodes/{id}/attributes`, `GET .../next-question?fy=2025-26` and
`GET .../snapshot?fy=2025-26`. `CW_PROFILE_STORE=memory` runs the service without Postgres.

The public business API does the same in fewer calls. A creating POST needs an
`Idempotency-Key`; sending the same request with the same key again answers the first 201 with
`Idempotent-Replayed: true`, and another body with that key is a 422:

```bash
curl -s -X POST http://localhost:8002/v1/businesses \
  -H 'content-type: application/json' -H 'x-tenant-id: 5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a' \
  -H "Idempotency-Key: $(uuidgen)" -d '{"name":"Acme","gstin":"29ABCDE1234F1Z5"}'
curl -s 'http://localhost:8002/v1/businesses?limit=20' -H 'x-tenant-id: 5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a'
curl -s http://localhost:8002/v1/ontology | jq '.attributes[0].question, .operators_by_type.enum'
```

`GET /v1/businesses/{id}/onboarding` asks the next question with its labelled options, and
`PATCH /v1/businesses/{id}` stores answers. These routes are in the public API spec,
`packages/contracts/openapi/public.v1.json` (`make openapi-public`).

## Signing in with tokens

`CW_AUTH_MODE` decides how every Python service reads its caller (the py-common README,
"Authentication", has the details):

| Mode | What a service does |
| --- | --- |
| `header` (the default) | Reads no token. The tenant comes from `x-tenant-id` and shared secrets guard the service-to-service routes, as in the examples above. |
| `dual` | Verifies a bearer token when a request carries one and enforces its tenant, roles and scopes; a request without one is served as in `header` mode. |
| `token` | Needs a bearer token wherever a caller is read: every tenant route and every service-to-service route. Shared secrets open nothing. `CW_ENV=prod` accepts only this mode. |

Locally, identity signs people in with a fake identity provider (`CW_AUTH_PROVIDER=fake`, the
default), so no account is needed. With both services on memory stores, no container is needed
either:

```bash
export DEV_CLIENT_SECRET=$(openssl rand -hex 24)   # the dev service clients' secret
# optional: tokens that survive identity's reload (see below)
export CW_IDENTITY_SIGNING_KEYS="$(uv run --package compliancewatch-identity \
  identity-admin signing-key new --kid dev | jq -c .)"
CW_IDENTITY_STORE=memory CW_AUTH_MODE=token CW_IDENTITY_DEV_CLIENT_SECRET=$DEV_CLIENT_SECRET \
  make run SERVICE=identity
CW_PROFILE_STORE=memory CW_AUTH_MODE=token make run SERVICE=profile   # in a second shell
```

Then, with identity on 8001 and profile on 8002:

```bash
ID=http://localhost:8001/v1/identity
provider_token() {   # a fake provider token for a phone number; add "aal":"aal2" for a second factor
  curl -s -X POST $ID/dev/provider-tokens -H 'content-type: application/json' \
    -d "{\"phone\":\"$1\"}" | jq -r .provider_token
}
# A person nobody has signed up yet: 404 identity-user-not-provisioned, the cue to sign up
curl -s -X POST $ID/sessions -H 'content-type: application/json' \
  -d "{\"provider_token\":\"$(provider_token +919876543210)\"}" | jq .type
# Sign-up creates the business tenant with the person as its owner, and answers a session
curl -s -X POST $ID/tenants -H 'content-type: application/json' \
  -d "{\"kind\":\"business\",\"name\":\"Acme Traders\",\"provider_token\":\"$(provider_token +919876543210)\"}" \
  | jq '{tenant: .tenant.id, roles: .user.roles}'
# Sign-in exchanges a provider token for an ES256 access token (ten minutes)
TOKEN=$(curl -s -X POST $ID/sessions -H 'content-type: application/json' \
  -d "{\"provider_token\":\"$(provider_token +919876543210)\"}" | jq -r .access_token)
curl -s $ID/me -H "authorization: Bearer $TOKEN" | jq '{tenant: .tenant.id, roles, session_version, mfa}'
# Profile: 201 with the token, 401 auth-token-required without it,
# and 403 auth-tenant-mismatch when x-tenant-id names another tenant
curl -s -X POST http://localhost:8002/v1/profile/registrations \
  -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"gstin":"29ABCDE1234F1Z5","name":"Acme Bengaluru","entity_name":"Acme"}'
# A service token for the pipeline's dev client
curl -s -X POST $ID/service-tokens -H 'content-type: application/json' \
  -d "{\"client_id\":\"pipeline\",\"client_secret\":\"$DEV_CLIENT_SECRET\"}" | jq '{scopes, expires_in}'
```

- Every other service fetches identity's public keys from `CW_AUTH_JWKS_URL`, by default
  `http://localhost:8001/v1/identity/.well-known/jwks.json`; a second clone points it at its own
  identity port.
- Without `CW_IDENTITY_SIGNING_KEYS`, identity makes a key when it starts and logs
  `identity_ephemeral_signing_key`. Every token it signed stops verifying when it restarts, which
  `make run` does on each code change. The key set exported above lives in that shell only; never
  reuse a dev key in another environment.
- A caller sends its own service token once `CW_SERVICE_CLIENT_SECRET` is set to the dev secret
  (`make run` and `make worker` set `CW_SERVICE_CLIENT_ID` to the service's name; an empty id
  stands for the process's service name, so the other targets start with the secret in `.env`).
  The dev clients and their scopes are in
  `services/identity/src/identity/identity_dev_clients.toml`; the WhatsApp bot reads
  `BOT_SERVICE_CLIENT_ID` and `BOT_SERVICE_CLIENT_SECRET` from `apps/whatsapp-bot/.env`.
- The web app sends no tokens yet, and `make web-stack` reads `.env`: keep `CW_AUTH_MODE` out of
  `.env`, or at `header`, while you run the web app.
- `tools/demo/tests/unit/test_token_flow.py` runs the same steps in one process.

## Seed calendar

`make migrate SERVICE=rulebook` then `make seed SERVICE=rulebook` loads the thirteen standing
GST obligations from `services/rulebook/seed/gst_calendar.yaml` as draft rule versions
(`select rule_key, version, status, seed_status from rulebook.rule_version join rulebook.rule
on rule.id = rule_id` through `make dev-psql`). `ARGS=--check` validates the file without
writing. Every version stays `needs_review` until an analyst reviews it.

## Row-level security in the dev stack

Tenant tables (the obligation service's first) carry a policy on `tenant_id`, but `make run`,
`make worker` and `make web-stack` connect as `cw`, the container's superuser, and a superuser
bypasses every policy. The policy is therefore visible but not enforced there, and the services
whose queries leave the tenant to the policy (profile, the engine, obligation) read across
tenants; the integration tests prove the policies through a plain role. `make product` connects
as `cw_app`, a role that owns nothing and is not a superuser (`make product-role`), so the
policies apply to the local product. A role per service arrives with the deployment work.

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

## Running a second clone

A second working copy of the repository on the same machine needs its own containers and
ports. In its root `.env`, give `COMPOSE_PROJECT_NAME` another value (compose names the
containers, network and volumes after it, so the two stacks never share a database; the
variable wins over the `name:` in `docker-compose.yml`, which is never edited for this) and
move every host port from the table above, plus `WEB_PORT`. The values a second copy uses:
Postgres 25432, Redis 26379, Kafka 39092 (schema registry 28081, admin 29644), Temporal 27233
(UI 28233), the collector on 24317 and 24318 (health 23133), Prometheus 29090, Grafana 23030,
Langfuse 23010, the fake LLM gateway 28090, the services on 9201 to 9210
(`make run SERVICE=identity PORT=9201`, in the `SERVICES` order of the Makefile), the web app
on 3200 (`WEB_PORT=3200`, which `make web-dev` and `make web-e2e` read) and the bot on 9180.
Rewrite `CW_DATABASE_URL`, `CW_REDIS_URL`, `CW_KAFKA_BOOTSTRAP`, `CW_TEMPORAL_ADDRESS` and the
`CW_*_URL` service URLs to those ports as well. `make web-e2e` needs no container at all: it
builds the app and runs Playwright against `next start` on `WEB_PORT`.

The services behind the web app come up together with `make web-stack`, the UI-only stack (no
worker, so no decision becomes obligations or a message there; `make product` is the full
product, [product.md](product.md)): every service on
`SERVICE_PORT_BASE`+1 to +10 in the `SERVICES` order (8001 to 8010 with the example `.env`;
`SERVICE_PORT_BASE=9200` in a second copy), each given the others' addresses on those ports
whatever `.env` says, on memory stores so no container is needed, with
the profile's static GSTIN lookup, the billing provider `none` (`BILLING=memory` for a
subscription demo), the KAG layer off, and the rulebook publishing with its write and review
tokens from `.env` or the placeholders `local-write-token` and `local-review-token` and, on the
memory store, starting with the seed calendar's drafts (`CW_RULEBOOK_SEED_ON_START`, local and
test only; with `STORE=postgres`, `make seed SERVICE=rulebook` writes them);
pids and logs land in `var/web-stack`. `make web-stack-wait` waits for every `/health`,
`make web-stack-logs SERVICE=identity` tails one log, `make web-stack-down` stops them all
(memory stores forget their rows then; `STORE=postgres` runs the stores on the compose
Postgres after `make dev` and `make migrate`). The web app reaches the stack through the
`CW_WEB_*_URL` values in `apps/web/.env.local` (`http://localhost:9201` onward in a second copy).
`make web-seed` fills the running stack with the demo tenant through the services' HTTP APIs
(consents, the demo GSTIN's registration, pre-fill and answers, the WhatsApp preference with the
opt-in confirmation sent to it, and one
recorded CBIC notification with its clauses, mentions and relation candidate for the admin
review queues), records it in `var/seed/last.json` for the development sign-in, and exits
non-zero when a step fails; run it again after every `make web-stack`, since memory stores start
empty. `make web-e2e` after the seed also runs the seeded-tenant sign-in test, which is skipped
without it; CI's `web-e2e` job starts the stack and seeds it before Playwright in the same order.

## Not in the stack yet

Seeded fixtures and the 50-document sample rulebook, Keycloak, Terraform, alert rules.

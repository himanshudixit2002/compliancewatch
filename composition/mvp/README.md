# compliancewatch-mvp

The composition root of ADR-013: every service in one deployable. It lives under
`composition/` rather than `infra/` (the root `.dockerignore` drops `infra`) and is not named
`platform` (a standard library module). It may import every service, as `tools/demo` does; no
service or shared package imports it (an import-linter contract holds that).

## The app process: `cw-mvp serve`

One uvicorn process runs one FastAPI app per service behind one ASGI dispatcher
(`cw_mvp.dispatch`), on two listeners that both bind `CW_MVP_HOST` (`::`, IPv4 included):

| Listener | Port | Reached by | Serves |
| --- | --- | --- | --- |
| public | `CW_MVP_PUBLIC_PORT` (8000) | the edge | `/health`, `/ready` and the routes `cw_mvp.exposure` classes public; the admin ones too with `CW_AUTH_MODE=token` |
| internal | `CW_MVP_INTERNAL_PORT` (8080) | the private network only | every route |

Anything else on the public listener, and any path no service owns, is a 404
`route-not-found` problem. `/ready` reports every service's checks as `<service>.<check>`.

- **Registry** (`cw_mvp.registry`): one entry per `services/` directory with its schema,
  settings class, `build_app`, worker components, URL settings and the routes that call other
  services. Each service gets its own settings: the shared `CW_*` settings, its schema
  first on the `search_path`, and every URL of another service at `CW_MVP_INTERNAL_URL`. Every
  hosted service connects with the one `CW_DATABASE_URL`, so the process runs as one role with
  every service schema (`cw_app` locally, `infra/dev/postgres/50-app-role.sql`). The separate
  processes of `make run` connect as each service's own role, `cw_<schema>`
  (`infra/dev/postgres/roles.sql`); doing the same here needs a URL per service in the registry,
  one pool each, which is deploy work for package M5-2.
- **Exposure** (`cw_mvp.exposure`): every route's class, public, admin or internal. A route
  without one is not served publicly, and the unit tests fail until it has one.
- **Tokens**: identity is built first. Every other service verifies callers with identity's
  authenticator, and outside `header` mode the services that call others send tokens minted in
  the process by identity's issuer, with the scopes of `CW_MVP_SERVICE_SCOPES` (the committed
  dev clients when it is empty). The app needs no client secrets.
- **Calls between services** go over the internal listener. Their routes are sync and hold a
  thread while they wait, so the app raises the thread pool to `CW_MVP_THREAD_TOKENS` (200) and
  runs at most `CW_MVP_LOOPBACK_LIMIT` (32) of the routes that make such calls at once: qa's
  `POST /v1/qa/ask` and the public `POST /v1/qa`, the engine's evaluation and its dry run,
  obligation's detail and assignee routes and the public list of a business's obligations,
  notification's bulk change card, and, only when `identity.plan_limits` can be on in the process
  (`CW_PLAN_LIMITS_ENFORCED` true, or the Unleash provider), profile's three routes that may add
  a GSTIN registration (they read the tenant's entitlements at identity while the flag is on;
  with it off they call nothing and are not counted). The
  routes they call make none themselves: qa and notification read obligation's list, which calls
  nothing, and the engine, obligation and qa read profile's node, snapshot and business, which
  call nothing either (`called_routes` in the registry); every service may call identity.
- **Dispatch**: a public path outside every service's prefix, such as `/v1/businesses` (profile)
  or `/v1/businesses/{business_id}/obligations` (obligation), is matched longest template first;
  any other path goes to the service its first segment names, so `/v1/qa` is qa's and
  `/v1/notification/bulk` notification's.

The services whose routes do more than read their own store:

- **applicability-engine**: a tenant's members read its decisions on the public listener
  (`GET /v1/applicability-engine/businesses/{business_id}/decisions` and
  `GET /v1/applicability-engine/decisions/{decision_id}`), and in the public API what a change
  means for their businesses (`GET /v1/changes/{rule_version_id}/impact`, beside the rulebook's
  `GET /v1/changes`), which reads the engine's own tables only. Evaluating,
  `POST /v1/applicability-engine/businesses/{business_id}/decisions`, is internal: it reads the
  profile snapshot and the rule version over the internal listener, and outside `header` mode
  with the token of the `applicability-engine` dev client, whose tenant:act lets it read the
  tenant's profile. The review queue (`GET /v1/applicability-engine/review-items` and
  `POST /v1/applicability-engine/review-items/{item_id}/resolve`) is admin: the regulatory team
  reads any tenant's items, naming the tenant in `x-tenant-id`, and a reviewer or admin settles
  one, which appends a decision that makes or closes obligations. The fan-out routes
  (`GET /v1/applicability-engine/fan-outs`, one run, its pause, resume and cancel, and
  `GET`/`PUT /v1/applicability-engine/fan-out-hold`) are admin too: the regulatory team reads the
  runs, and an admin controls them, each control audited and then signalled to the run's
  Temporal workflow (`CW_TEMPORAL_*`, with `CW_APPLICABILITY_FANOUT_ENABLED`). An admin's dry run,
  `POST /v1/applicability-engine/dry-runs`, is admin as well: it reads the rule version and every
  profile of its scope over the internal listener, at most `CW_APPLICABILITY_DRY_RUN_MAX`
  businesses, and stores nothing but its audit entry. Each route requires a regulatory role a
  verified token names, so the public listener serves them in token mode only. The engine's worker recomputes a business on profile.updated and fans a published
  version out over the business directory (below).
- **eval**: the regulatory team reads the stored runs (`GET /v1/eval/runs`, admin). Starting
  one, `POST /v1/eval/runs`, is internal: it runs the harness in a child process, which spends
  compute and, under the nightly profile, model budget. That profile reaches the gateway at
  `CW_EVAL_GATEWAY_URL`, which the registry leaves alone (it is not named `<service>_url`), and
  the harness sends no token: a nightly run from the deployable needs that URL set to the
  internal listener, and a mode other than `token`.
- **obligation**: a tenant's members read obligations and track one on the public listener, under
  `/v1/obligation/obligations/{obligation_id}` and in the public API under
  `/v1/obligations/{obligation_id}`: the detail, its status, its assignee and its comments, each
  change with an Idempotency-Key and an audit row. The detail reads the rulebook over the internal
  listener when its cache lacks the rule version, and outside `header` mode an assignment asks
  identity's internal `GET /v1/identity/users/{user_id}/membership` whether the assignee belongs
  to the tenant, with the token of the `obligation` dev client (tenant:act). The public API's
  `GET /v1/businesses/{business_id}/obligations` lists one node's obligations a page at a time;
  when a page is empty it asks profile's `GET /v1/profile/nodes/{node_id}` whether the node is
  the tenant's (404 otherwise). The worker makes obligations from applicability decisions,
  closes or moves them on the rule events, and rolls their window (below).
- **notification**: the public `POST /v1/notification/bulk` sends a CA firm's change card to the
  clients a change affects (behind `CW_NOTIFICATION_BULK_ENABLED`); it reads each client's open
  obligations of the change from obligation's list over the internal listener, with the token of
  the `notification` dev client (tenant:act) outside `header` mode, queues the cards and writes
  its `notification.bulk` audit row.
- **qa**: `POST /v1/qa/ask` and the public `POST /v1/qa` run one handler, reading the profile, the
  business's obligations and the rulebook and calling the gateway over the internal listener.
- **pipeline**: the source manager is admin. The regulatory team reads the sources with how each
  stands, their documents and the stored files (`GET /v1/pipeline/sources`,
  `GET /v1/pipeline/sources/{key}/documents`, `GET /v1/pipeline/documents/{document_id}` and its
  `/raw`), and an admin adds and edits a source and starts a crawl
  (`POST /v1/pipeline/sources`, `PATCH /v1/pipeline/sources/{key}`,
  `POST /v1/pipeline/sources/{key}/fetch`, each audited); in `header` and `dual` mode the writes
  also take the shared write token `CW_RULEBOOK_WRITE_TOKEN`. A fetch starts the crawl workflow on
  Temporal (`CW_TEMPORAL_*`) and answers 503 while `CW_PIPELINE_CRAWL_ENABLED` is off.

The process must stay one process: notification preferences, the gateway's response cache and
its budget-alarm markers are still held in memory.

Tests and demos build the whole app without Postgres, and `running_app()` serves it on two free
local ports (`tools/demo/tests/unit/test_mvp_flow.py` onboards and evaluates a business on it):

```python
from cw_mvp.app import build_app
from cw_mvp.testing import MEMORY_SERVICES, mvp_settings

app = build_app(mvp_settings(), service_overrides=MEMORY_SERVICES)
```

## The worker process: `cw-mvp worker [--internal-url URL]`

One event loop runs every service's background work (`cw_mvp.worker`), each with that
service's settings:

| What | When |
| --- | --- |
| each service's worker components (`<pkg>.worker.components`): the engine's consumers of profile.updated and of rule.published and rule.withdrawn and its fan-out's Temporal worker (queue `applicability`), notification's consumer, dispatcher and retention sweep, obligation's consumers of applicability.decided and of the rule events, its reminder sweep and rolling window, the rulebook's daily transitions sweep and its consumer of rule.candidate.created, the pipeline's Temporal worker, its source sync at start and its crawl tick, and the erasure consumers: group `<service>.erasure` of tenant.deletion.requested in identity, profile, the rulebook, the engine, obligation and notification, and identity's `identity.erasure-records` of tenant.data.erased | consumers with `CW_WORKER_KAFKA_ENABLED`, Temporal workers with `CW_WORKER_TEMPORAL_ENABLED` (one client for all), periodic jobs always, behind their service's own switch: the reminder sweep and the rolling window with `CW_OBLIGATION_SWEEP_ENABLED`, the transitions with `CW_RULEBOOK_PUBLISH_ENABLED`, the rulebook's candidate intake (group `rulebook.rule-candidates`) only with Kafka and `CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED` (off in `make product`, so no group reads the candidates there), the pipeline's 60-second crawl tick with `CW_PIPELINE_CRAWL_ENABLED` (it crawls the live regulator sites, so it stays off in `make product` and CI); obligation's rules consumer acts on rule.published, rule.superseded, rule.withdrawn and rule.deadline_changed only with `CW_OBLIGATION_RULE_EVENTS_ENABLED` (it keeps its offsets either way); the engine's profile consumer runs with Kafka and evaluates only with `CW_APPLICABILITY_RECOMPUTE_ENABLED` (it keeps the business directory either way), and its rules consumer starts fan-outs only with `CW_APPLICABILITY_FANOUT_ENABLED` (it records a disabled run otherwise); the erasure consumers run with Kafka and erase only while the flag `identity.tenant_erasure` (`CW_TENANT_ERASURE_ENABLED`, per tenant with `CW_TENANT_ERASURE_TENANTS`) is on for the tenant, and only log `erasure.off` otherwise (docs/runbooks/data-requests.md) |
| one outbox relay per schema that has an `outbox_event` table | `CW_WORKER_KAFKA_ENABLED` |
| the daily idempotency purge of every schema that has an `idempotency_key` table | always |

Both switches are off by default. With Kafka on, a profile change reaches the engine's consumer
(group `applicability-engine.profiles`) through profile's relay; with recompute on, the engine
evaluates the changed business and the registrations under it against every rule in force,
reading the profile and the rulebook over the internal listener with no transaction open, and
the decisions it stores reach obligation's consumer through the engine's relay; the obligations
it makes reach notification's consumer through obligation's relay. The reminder sweep writes its
reminders to obligation's outbox, so they go out once a relay runs. The pipeline's ingest writes
each new document's document.discovered to the pipeline's outbox with its row, and the pipeline
schema's relay publishes it; nothing consumes it yet. A new consumer group reads a topic from its
earliest offset, so the engine's first run recomputes every profile.updated the broker still
holds.

The worker shares the services' state through Postgres. A service on its memory store
(`CW_OBLIGATION_STORE=memory` and the like) keeps its state in the app process, out of the
worker's reach, so the worker hosts nothing of it, not even its schema's relay or purge, and
logs `worker.service_skipped`; the service's own worker (`make worker SERVICE=obligation`)
refuses to start on that store instead.

The services call each other at `URL`, the app process's internal listener
(`CW_MVP_INTERNAL_URL` by default), as the `worker` service client (`CW_SERVICE_CLIENT_ID` and
`CW_SERVICE_CLIENT_SECRET`), whose tokens identity issues.

`/health` on `CW_MVP_WORKER_HEALTH_PORT` (8001) answers 200 while every hosted loop and task
queue runs and the heartbeat is fresh, 503 otherwise; `/loops` gives the detail. The health app
runs on its own thread, so it still answers while the worker's event loop is blocked. When one
loop fails it is logged, the others stop and the process exits 1, so the platform restarts it.

## Running it locally

`uv sync --all-packages` installs `cw-mvp`. Both processes read `CW_*` from the environment and
the repo's `.env`, as the services do. Bind `127.0.0.1` rather than every interface.

On memory stores, with nothing else running (the state goes when the process stops; the worker
has nothing to share it with):

```bash
CW_MVP_HOST=127.0.0.1 \
CW_IDENTITY_STORE=memory CW_PROFILE_STORE=memory CW_RULEBOOK_STORE=memory \
CW_APPLICABILITY_ENGINE_STORE=memory CW_OBLIGATION_STORE=memory \
CW_NOTIFICATION_STORE=memory CW_EVAL_STORE=memory CW_PIPELINE_STORE=memory \
uv run cw-mvp serve
curl -s 127.0.0.1:8080/ready                  # every service's checks
curl -s 127.0.0.1:8000/v1/businesses -H "x-tenant-id: $(uuidgen)"   # a public route
curl -s 127.0.0.1:8000/v1/eval/ping           # internal only: 404 route-not-found
```

On the dev stack (`make dev`, then `make migrate`; every `CW_<SERVICE>_STORE` defaults to
`postgres`, and `CW_DATABASE_URL` names the database whose schemas the services share):

```bash
CW_MVP_HOST=127.0.0.1 uv run cw-mvp serve
CW_MVP_HOST=127.0.0.1 CW_MVP_WORKER_HEALTH_PORT=8011 \
CW_WORKER_KAFKA_ENABLED=true CW_WORKER_TEMPORAL_ENABLED=true \
uv run cw-mvp worker
```

The ports are settings, not options: `CW_MVP_PUBLIC_PORT`, `CW_MVP_INTERNAL_PORT` (then
`CW_MVP_INTERNAL_URL` too) and `CW_MVP_WORKER_HEALTH_PORT`, whose default 8001 is identity's
port under `make run` and `make web-stack`. Outside `header` mode the worker sends tokens only
with `CW_SERVICE_CLIENT_SECRET` set: locally the `CW_IDENTITY_DEV_CLIENT_SECRET` identity creates
its dev clients, `worker` among them, with.

`make product` does all of this on the dev stack with Kafka and Temporal on, recompute on, the
worker's health on 8081, the services connecting as `cw_app` so row-level security applies, the
notification sink in place of the real channels, and the web app beside them;
`make product-seed` and `make product-check` fill it and prove the chain from a published rule
to a change card, and from a profile change to new decisions and obligations
([docs/onboarding/product.md](../../docs/onboarding/product.md)). `make product-image` runs the
same product from the image below, in containers.

## The image

`composition/mvp/Dockerfile` builds one image for both processes and the release step, chosen
by command:

```bash
docker build -f composition/mvp/Dockerfile -t compliancewatch-mvp:local .   # or make mvp-image
docker run ... compliancewatch-mvp:local                    # cw-mvp serve, the default
docker run ... compliancewatch-mvp:local cw-mvp worker      # the worker
docker run ... compliancewatch-mvp:local cw-mvp release     # once per version, before both
docker run ... compliancewatch-mvp:local cw-mvp check-config
```

It follows the services' images: a uv builder stage that installs the locked third-party
dependencies first and the workspace second, without the dev group, and a `python:3.12-slim`
runtime with the virtual environment, no uv, and the user `app` (uid 10001). The code belongs to
root, so the process cannot change it. Ports: 8000 (public), 8080 (internal), 8001 (the
worker's health).

The services read files beside their sources at runtime, so, as the eval image does, the
workspace is installed editable and the sources keep their paths under `/app`: the gateway's
prompt registry (`services/llm-gateway/prompts`), the qa and pipeline prompts, the rulebook's seed
calendar (`services/rulebook/seed`), every service's `alembic.ini` and migrations, this
directory's `topics.toml`, and the eval harness (`evals/harness`) with the golden set
(`evals/golden`), which the eval service runs in a child process. The ontology's YAML and the
contracts client (`cw_contracts`) are inside their packages. Tests, docs, `infra`, `tools`, the
web app, `var`, `output` and every `.env` stay out of the build context (`.dockerignore`), and the
image holds no secret: everything sensitive comes from the environment.

It is about 118 MB compressed and 420 MB unpacked: the Python base is 150 MB of that and the
virtual environment 274 MB (temporalio, SQLAlchemy, the OpenAI SDK, gRPC and uvloop are the
largest), the sources and data under 7 MB.

## Releasing: `cw-mvp release`

`cw-mvp release` is the step a deploy runs once per version, before the new app and worker
start: `cw-mvp migrate`, then `cw-mvp topics apply`, and nothing else. Both parts are idempotent,
so a second release changes nothing. With `CW_WORKER_KAFKA_ENABLED` off it skips the topics:
nothing reads or writes them, and a deployment without a broker still releases. Each command
exits 1 with the reason on stderr; settings a settings class refuses are listed the way
`check-config` lists them.

### `cw-mvp migrate [--service NAME]`

Runs `alembic upgrade head` for every service schema in the registry's order (identity first,
since its migration creates `audit.event`), or for one service, each in a child process with its
own `alembic.ini`, as `make migrate` does. It connects as the role that owns the schemas,
`CW_MIGRATION_DATABASE_URL` (a secret), and never as the app's runtime role
(`CW_DATABASE_URL`): it refuses to run without the owner's URL, and outside local and test it
refuses when both URLs connect as the same role to the same database. A schema the database lacks
is created first, so a new managed database needs nothing else (the rulebook's migration creates
the `vector` extension; the owner needs the right to). It reports what ran:

```
migrate: as cw on compliancewatch at postgres:5432 (CW_MIGRATION_DATABASE_URL)
  identity               schema identity       at 0005, nothing to run
  rulebook               schema rulebook       0006 -> 0007
  qa                     schema qa             no migrations
  ...
migrate: 10 services, 1 migrated, 9 unchanged
```

A failed migration stops the run with the end of alembic's output; the services after it are
not migrated. A migration must keep working with the previous image, which serves until the new
one starts (expand, then contract in a later release).

### Topics: `cw-mvp topics plan|apply`

`topics.toml` lists the Kafka topics as code: every contract topic
(`packages/contracts/events/schemas`) and the dead-letter topic of every consumer group the
worker hosts (`<topic>.<group>.dlq`), each with its partitions, retention and cleanup policy, and
one replication factor (3, capped at the brokers the cluster reports, so 1 on the dev stack).
`tests/unit/test_topics_file.py` fails when a contract topic or a consumer group's dead-letter
topic is missing, or when the file lists a topic that is neither.

| Topics | Partitions | Retention | Why |
| --- | --- | --- | --- |
| tenant events: `applicability.decided`, `obligation.*`, `profile.updated`, `notification.*`, `tenant.*`, `user.role.changed` | 3 | 7 days | keyed by tenant, so three workers can share a group without re-keying; a week covers a worker down over a long weekend |
| regulatory and platform events: `rule.*`, `rule.candidate.created`, `document.*`, `eval.run.completed` | 1 | 30 days | a few a day, kept in publication order; a consumer that fell behind still sees a month of changes |
| dead letters, `<topic>.<group>.dlq` | 1 | 30 days | time to read, fix and replay |

Every topic is a log of events with `cleanup.policy=delete`. A consumer group made later reads
only what a topic still holds, the engine's business directory (built from `profile.updated`)
among it. The relay's own dead letters, `<topic>.dlq`, are not listed: a row whose topic cannot be
reached stays in its outbox and is retried, so nothing is lost while one is missing.

`cw-mvp topics plan` compares the file with the broker of `CW_KAFKA_*` (SASL and TLS included,
through `py_common.kafka.KafkaClientConfig`); `cw-mvp topics apply` creates the topics the broker
lacks. Neither deletes or changes a topic: one the file does not list is left alone, and one whose
partitions, `retention.ms` or `cleanup.policy` differ is reported and left as it is, since adding
partitions moves keys between them. An operator settles those with `rpk topic add-partitions` or
`rpk topic alter-config`. `--file` reads another file.

### `cw-mvp check-config`

Checks the environment (and `.env`) against its `CW_ENV` and lists every problem as
`<where>: <problem>`, exiting 1 when there is one; it prints no secret. Run it where the deploy's
settings are, before the release. It builds the settings as the app does, so each settings class
reports its own rules in its own words: production takes only `CW_AUTH_MODE=token` and refuses
identity's `fake` sign-in, staging and production need `CW_IDENTITY_SIGNING_KEYS`, the dev
clients' secret, the notification `sink`, and the seed calendar loaded at start are for local and
test only, and a provider that needs credentials (Supabase, Vercel's gateway, the HTTP GSTIN
lookup, Unleash, Kafka over SASL, a Temporal certificate) has them. A class stops at its first
refusal, so fixing one can bring the next to light. In staging and production it also refuses:

- `CW_AUTH_MODE=header` in staging, which runs `dual` and then `token` before production;
- `CW_LOG_JSON=false`: the console renderer formats a traceback after the masking, so its
  personal identifiers would reach the log collector as they are;
- fake providers: `CW_LLM_PROVIDER=fake` (with `CW_LLM_RESIDENCY=india_only` too, which refuses
  every real model call and is accepted as the maintainer's choice), `CW_AUTH_PROVIDER=fake` in
  staging, `CW_PROFILE_GSTIN_LOOKUP=static` (the demo table) and `CW_BILLING_PROVIDER=memory`;
- memory stores: every `CW_<SERVICE>_STORE=memory` and `CW_LLM_LEDGER=memory`;
- a rulebook that would accept synthetic approvals;
- placeholder secrets: `local-write-token`, `local-review-token`, or a `dev-only` value in any
  secret setting;
- missing secrets an enabled feature needs: WhatsApp's number id and token
  (`CW_WHATSAPP_ENABLED`), email's host, sender, feedback token and, with a username, password
  (`CW_EMAIL_ENABLED`), Razorpay's keys, `CW_RULEBOOK_REVIEW_TOKEN` for publishing and
  `CW_RULEBOOK_WRITE_TOKEN` for the pipeline's knowledge step outside token mode, and in token
  mode the worker's `CW_SERVICE_CLIENT_SECRET` while its Kafka or Temporal switch is on;
- a pipeline raw store other than `s3` (`CW_PIPELINE_RAW_STORE=local` or `memory`) while the
  worker fetches regulator documents, which it does with `CW_WORKER_TEMPORAL_ENABLED` or
  `CW_PIPELINE_CRAWL_ENABLED` on (`check_config.fetch_switches` lists the switches): the files
  would go with the machine. The
  pipeline's own settings refuse `s3` without its bucket and key, and unencrypted files
  (`CW_PIPELINE_RAW_ENCRYPTION=none`) in staging and production.

## Adding to a service

A change that adds a route, `build_app` argument, worker component or URL of another service
registers it here in the same change: the route's class in `exposure.py`, the rest in
`registry.py`. `tests/unit/test_exposure.py` and `tests/unit/test_registry.py` fail until it
does. A store setting is named `<service>_store`, so the worker finds it, and goes into
`cw_mvp.testing.MEMORY_SERVICES`; a setting that picks where a service keeps files rather than
its state ends in `_raw_store` (`pipeline_raw_store`), and check-config has a rule for it. A new
event topic or consumer group goes into `topics.toml` (`tests/unit/test_topics_file.py`), and a
file a service reads at runtime stays beside its sources and inside the build context
(`.dockerignore`).

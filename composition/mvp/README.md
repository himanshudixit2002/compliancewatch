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
  first on the `search_path`, and every URL of another service at `CW_MVP_INTERNAL_URL`.
- **Exposure** (`cw_mvp.exposure`): every route's class, public, admin or internal. A route
  without one is not served publicly, and the unit tests fail until it has one.
- **Tokens**: identity is built first. Every other service verifies callers with identity's
  authenticator, and outside `header` mode the services that call others send tokens minted in
  the process by identity's issuer, with the scopes of `CW_MVP_SERVICE_SCOPES` (the committed
  dev clients when it is empty). The app needs no client secrets.
- **Calls between services** go over the internal listener. Their routes are sync and hold a
  thread while they wait, so the app raises the thread pool to `CW_MVP_THREAD_TOKENS` (200) and
  runs at most `CW_MVP_LOOPBACK_LIMIT` (32) of the routes that make such calls at once: qa's
  `POST /v1/qa/ask` and the engine's evaluation. The services they call make none themselves.

The services whose routes do more than read their own store:

- **applicability-engine**: a tenant's members read its decisions on the public listener
  (`GET /v1/applicability-engine/businesses/{business_id}/decisions` and
  `GET /v1/applicability-engine/decisions/{decision_id}`). Evaluating,
  `POST /v1/applicability-engine/businesses/{business_id}/decisions`, is internal: it reads the
  profile snapshot and the rule version over the internal listener, and outside `header` mode
  with the token of the `applicability-engine` dev client, whose tenant:act lets it read the
  tenant's profile. The review queue (`GET /v1/applicability-engine/review-items` and
  `POST /v1/applicability-engine/review-items/{item_id}/resolve`) is admin: the regulatory team
  reads any tenant's items, naming the tenant in `x-tenant-id`, and a reviewer or admin settles
  one, which appends a decision that makes or closes obligations. Each route requires a
  regulatory role a verified token names, so the public listener serves them in token mode
  only. The engine's worker recomputes a business on profile.updated (below).
- **eval**: the regulatory team reads the stored runs (`GET /v1/eval/runs`, admin). Starting
  one, `POST /v1/eval/runs`, is internal: it runs the harness in a child process, which spends
  compute and, under the nightly profile, model budget. That profile reaches the gateway at
  `CW_EVAL_GATEWAY_URL`, which the registry leaves alone (it is not named `<service>_url`), and
  the harness sends no token: a nightly run from the deployable needs that URL set to the
  internal listener, and a mode other than `token`.
- **obligation**: the API only reads obligations; the worker makes them from applicability
  decisions (below).

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
| each service's worker components (`<pkg>.worker.components`): the engine's consumer of profile.updated, notification's consumer, dispatcher and retention sweep, obligation's consumer of applicability.decided and reminder sweep, the rulebook's daily transitions sweep, the pipeline's Temporal worker | consumers with `CW_WORKER_KAFKA_ENABLED`, Temporal workers with `CW_WORKER_TEMPORAL_ENABLED` (one client for all), periodic jobs always, behind their service's own switch: the reminder sweep with `CW_OBLIGATION_SWEEP_ENABLED`, the transitions with `CW_RULEBOOK_PUBLISH_ENABLED`; the engine's consumer runs with Kafka and evaluates only with `CW_APPLICABILITY_RECOMPUTE_ENABLED` (it keeps the business directory either way) |
| one outbox relay per schema that has an `outbox_event` table | `CW_WORKER_KAFKA_ENABLED` |
| the daily idempotency purge of every schema that has an `idempotency_key` table | always |

Both switches are off by default. With Kafka on, a profile change reaches the engine's consumer
(group `applicability-engine.profiles`) through profile's relay; with recompute on, the engine
evaluates the changed business and the registrations under it against every rule in force,
reading the profile and the rulebook over the internal listener with no transaction open, and
the decisions it stores reach obligation's consumer through the engine's relay; the obligations
it makes reach notification's consumer through obligation's relay. The reminder sweep writes its
reminders to obligation's outbox, so they go out once a relay runs. A new consumer group reads a
topic from its earliest offset, so the engine's first run recomputes every profile.updated the
broker still holds.

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
CW_NOTIFICATION_STORE=memory CW_EVAL_STORE=memory \
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
([docs/onboarding/product.md](../../docs/onboarding/product.md)).

## Adding to a service

A change that adds a route, `build_app` argument, worker component or URL of another service
registers it here in the same change: the route's class in `exposure.py`, the rest in
`registry.py`. `tests/unit/test_exposure.py` and `tests/unit/test_registry.py` fail until it
does. A store setting is named `<service>_store`, so the worker finds it, and goes into
`cw_mvp.testing.MEMORY_SERVICES`.

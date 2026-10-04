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
  runs at most `CW_MVP_LOOPBACK_LIMIT` (32) of the routes that make such calls at once; the
  services they call make none themselves.

The process must stay one process: notification preferences, the gateway's response cache and
its budget-alarm markers are still held in memory.

Tests and demos build the whole app without Postgres:

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
| each service's worker components (`<pkg>.worker.components`): notification's consumer, dispatcher and retention sweep, the rulebook's daily transitions sweep, the pipeline's Temporal worker | consumers with `CW_WORKER_KAFKA_ENABLED`, Temporal workers with `CW_WORKER_TEMPORAL_ENABLED` (one client for all), periodic jobs always |
| one outbox relay per schema that has an `outbox_event` table | `CW_WORKER_KAFKA_ENABLED` |
| the daily idempotency purge of every schema that has an `idempotency_key` table | always |

Both switches are off by default. The services call each other at `URL`, the app process's
internal listener (`CW_MVP_INTERNAL_URL` by default), as the `worker` service client
(`CW_SERVICE_CLIENT_ID` and `CW_SERVICE_CLIENT_SECRET`), whose tokens identity issues.

`/health` on `CW_MVP_WORKER_HEALTH_PORT` (8001) answers 200 while every hosted loop and task
queue runs and the heartbeat is fresh, 503 otherwise; `/loops` gives the detail. The health app
runs on its own thread, so it still answers while the worker's event loop is blocked. When one
loop fails it is logged, the others stop and the process exits 1, so the platform restarts it.

## Adding to a service

A change that adds a route, `build_app` argument, worker component or URL of another service
registers it here in the same change: the route's class in `exposure.py`, the rest in
`registry.py`. `tests/unit/test_exposure.py` and `tests/unit/test_registry.py` fail until it
does.

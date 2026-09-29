# py-common package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing and metrics (OpenTelemetry), config, auth middleware, problem details, cursor pagination, idempotency keys, feature flags, outbox, Temporal worker scaffold, testing fakes
- **Owning team:** Platform and Infrastructure
- **Consumes:** n/a
- **Emits / publishes:** Golden-path library consumed by every Python service

## Layout

```
src/py_common/
  settings.py          # pydantic-settings, env_prefix CW_, env_file .env
  flags.py             # configure_flags, flag_enabled, flag_value: OpenFeature over the flag registry (env or Unleash)
  flags_registry.json  # generated from packages/flags/registry.json by make flags; never edited by hand
  logging.py           # structlog JSON logging bridging stdlib records; correlation_id/tenant_id/actor contextvars
  health.py            # GET /health and GET /ready router with pluggable readiness checks
  request_context.py   # x-request-id middleware; correlation_id_of(request) for handlers and dependencies
  problems.py          # RFC 9457 problem+json handlers, Problem schema, problem_responses() for routers
  pagination.py        # keyset pagination: Pagination (limit, cursor), encode/decode_cursor, Page[T], page_of
  app.py               # create_app(service_name, version, routers, problem_status, authenticator, ...)
  auth/                # verified identities; the package itself loads no FastAPI
    keys.py            # ES256 SigningKey, KeySet (first signs, all published), load_signing_keys
    tokens.py          # TokenIssuer, TokenVerifier (ES256 only), JwksUrlSource (1 h cache), StaticKeySource
    errors.py          # 401 token required, 401 token invalid, 403 forbidden, 403 tenant mismatch, 503 keys unavailable
    context.py         # current_principal, bind_principal: actor and tenant_id in the log context
    fastapi.py         # Authenticator by CW_AUTH_MODE, authenticate, tenant_scope, require_roles, shared_token_or_roles
    service_tokens.py  # ServiceTokenSource (cached until a minute before expiry), BearerAuth, service_auth_from
    testing.py         # TestIssuer: tokens signed with a key generated at run time; bearer(token)
  telemetry.py         # configure_telemetry (OTLP to CW_OTEL_ENDPOINT), instrument_app, instrument_engine
  temporal/
    client.py          # connect(settings): pydantic converter + tracing interceptor
    activity.py        # ActivityBase: validate/run/record, retry policy and timeouts on the class, schedule()
    worker.py          # WorkerConfig, build_worker, run_worker (stops on SIGTERM/SIGINT)
    liveness.py        # running(task_queue): the temporal_worker_up{task_queue} gauge while a worker runs
  events.py            # EventMessage (the envelope), to_message/encode/decode, payload_of(event)
  migrations.py        # alembic helpers: enable_tenant_rls, create_append_only_guard and their drop twins
  runtime.py           # WorkerComponents (consumers, relays, periodic jobs, Temporal workers); run_worker_process
  outbox/
    schema.py          # outbox_event and processed_event tables; create_*/drop_* helpers for alembic
    writer.py          # OutboxWriter.write(connection, event): the row commits with the state change
    store.py           # store protocols; PostgresOutboxStore (FOR UPDATE SKIP LOCKED), PostgresProcessedStore
    producer.py        # MessageProducer protocol; AiokafkaProducer (idempotent, acks=all)
    relay.py           # OutboxRelay: publish, retry with backoff, dead-letter; python -m py_common.outbox
    consumer.py        # IdempotentConsumer: once per event id and consumer group, consumer dead-letter topic
    sync.py            # SyncProcessedStore and sync_handler: sync handlers in the unit's transaction; run_consumer
    testing.py         # FakeProducer, MemoryOutboxStore, MemoryProcessedStore for service tests
  idempotency/         # Idempotency-Key with 24 hour replay; the package itself loads no FastAPI or SQLAlchemy
    store.py           # fingerprint, the begin outcomes, IdempotencyStore and IdempotencyRecorder protocols
    memory.py          # MemoryIdempotencyStore
    sqlalchemy.py      # SqlAlchemyIdempotencyStore (own transactions); SqlAlchemyIdempotencyRecorder (the caller's)
    schema.py          # idempotency_key: create/drop_idempotency_table(op), forced tenant policy, purge policy
    fastapi.py         # IdempotencyKey dependency, run_idempotent, IDEMPOTENCY_RESPONSES
    errors.py          # 428 key required, 422 key reused, 409 request in flight
    __main__.py        # python -m py_common.idempotency purge
tests/unit/
tests/integration/     # the outbox against Postgres and Redpanda, the migration helpers and idempotency keys on Postgres, flags on an Unleash server (testcontainers)
```

## Problem details

Every error a service returns is `application/problem+json` (RFC 9457) with `type`, `title`,
`status`, `detail`, `instance` and `correlation_id`. `create_app` installs the handlers for
every app. A `DomainError` maps to the status the service passes in `problem_status`, for
example `{BudgetExceededError: 429}`; the most specific class in the error's MRO wins, the
defaults (`InvariantViolationError` 422, `UnknownAttributeError` 404, and py-common's own
`InvalidCursorError` 422, idempotency errors 428, 422 and 409, `UnknownFlagError` 500, and
the authentication errors 401, 403 and 503)
apply underneath, and an unmapped domain error is a 400. An error class may define `problem_headers` (a mapping) and
those headers are copied onto the response; the gateway's budget error sets `Retry-After` that
way. Request validation errors are 422 with an `errors` list that does not echo the submitted
value, `HTTPException` keeps its status with type `about:blank`, and an unhandled exception is
a generic 500 that is logged with the correlation id. Routers declare the shape in OpenAPI with
`responses=problem_responses(422, 429)`; the `Problem` schema is published under
`components.schemas` automatically. Two responses every route can give are documented without
a declaration: the 422 of request validation is a `Problem` (FastAPI's default
`HTTPValidationError` entry is replaced), and every operation that takes a body lists a 400
for a body that is not UTF-8, which fails before validation runs.

## Authentication

The identity service issues ES256 access tokens and every service verifies them with
`py_common.auth`. A token names a `Principal` from `domain_kernel.access`: a user (`sub` the
user id, `tid` the tenant, `roles`, `mfa`, `sv` the session version) or a service client (`sub`
the client id, `scp` its scopes); `iss`, `aud`, `iat`, `exp` and `jti` complete the claims and
the header's `kid` names the signing key. `CW_AUTH_MODE` decides what a service does with them
(it is registered as the `auth.mode` flag):

- `header` (the default): no token is read and the tenant comes from `x-tenant-id`, as before;
- `dual`: a bearer token is verified and enforced when a request carries one, and a request
  without one is served as in `header` mode;
- `token`: every request needs a bearer token. `CW_ENV=prod` refuses any other mode.

`create_app` puts an `Authenticator` on `app.state`, built from the settings: keys come from
`CW_AUTH_JWKS_JSON` when it is set and otherwise from `CW_AUTH_JWKS_URL` (identity's
`/v1/identity/.well-known/jwks.json`), cached for an hour; a token naming a key the cache lacks
fetches once more, at most every 30 seconds, and cached keys stay in use while identity is
unreachable. With nothing cached and identity unreachable, a token cannot be checked:
`auth-keys-unavailable` (503), answered at once without another fetch for the next 5 seconds.
`CW_AUTH_ISSUER`, `CW_AUTH_AUDIENCE` and `CW_AUTH_LEEWAY_SECONDS` (30) complete the checks. Only
ES256 is accepted, so `none` and HS256 tokens are refused whatever key they name.

A route reads its caller through dependencies in `py_common.auth.fastapi`:

- `CurrentPrincipal` (`authenticate`): the principal, anonymous in `header` mode. A missing
  token in `token` mode is `auth-token-required` (401 with `WWW-Authenticate: Bearer`), a bad
  one `auth-token-invalid` (401). The principal is bound for the request, so every log line
  carries `actor` (`user:<uuid>`, `service:<client>` or `anonymous`) and, for a user,
  `tenant_id`.
- `tenant_scope(True, TenantRequiredError)`: the tenant. A user's token names it and an
  `x-tenant-id` naming another is `auth-tenant-mismatch` (403); a service names it in the
  header and needs the `tenant:act` scope; the anonymous principal names it in the header. No
  tenant is the service's own error, so its problem type does not change.
- `require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})`: a user with one of the roles
  or a service with one of the scopes, else `auth-forbidden` (403). The anonymous principal
  passes, so `header` mode behaves as before.
- `shared_token_or_roles(setting, header, roles, scopes, disabled_error=..., invalid_error=...)`:
  for routes a shared secret guarded. A bearer with one of the roles or scopes is accepted in
  `dual` and `token` mode; the secret is accepted only in `header` and `dual` mode and fails
  closed when unset. The two errors are the service's own.
- `Authenticated`: any verified principal; the anonymous one is a 401.

A service calls others with its own token. `CW_SERVICE_CLIENT_ID` and `CW_SERVICE_CLIENT_SECRET`
name its client at the identity service (`CW_IDENTITY_URL`). An empty id stands for the process's
service name, and `make run` and `make worker` set it to the service's directory name unless it is
set already, so a worker is its service's client. Every outgoing `httpx2` client is built with
`auth=service_auth_from(settings)`, which is None, so no token is sent, until the secret is set.
The token comes from `POST /v1/identity/service-tokens`, is kept until a minute before it expires
and is shared by the clients built from the same settings; a 401 from the called service drops it
and resends the request once with a fresh one. When identity cannot be reached or refuses the
client, the call fails with `service-token-unavailable` (503).

Tests use `py_common.auth.testing.TestIssuer`, which generates its key at run time:
`Settings(**issuer.settings_overrides("token"))` makes a service verify its tokens, and
`bearer(issuer.user(tenant, [Role.OWNER]))` or `bearer(issuer.service("pipeline", scopes))` is
the header. `py_common.auth` itself imports no FastAPI (an import-linter contract keeps it so),
so application layers may use the principal, the issuer and the key helpers.

`tools/demo/tests/unit/test_token_flow.py` puts the pieces together: identity signs a person's
token, the profile service verifies it with the key set identity publishes (inline, and fetched by
URL), and a `ServiceTokenSource` pointed at identity gets a service client's token. A deployment
moves from `header` to `dual` to `token` as ADR-014's addendum describes, and identity's signing
keys rotate as `docs/runbooks/secret-rotation.md` describes; a verifier holds the old and the new
key through a rotation because it fetches the key set again when a token names a key it lacks.

## Pagination

A list route declares `page: Pagination`, which reads `limit` (1 to 200, default 50) and
`cursor` (at most 512 characters) from the query, and answers a `Page[T]`: `items` and
`next_cursor`, null on the last page. The repository reads `limit + 1` rows in the order of a
unique key, starting after the keyset `page.after(scope, KeysetModel)` decodes, and
`page_of(rows, limit, scope, keyset)` keeps `limit` of them and makes the next cursor from the
last one when the extra row came back. A cursor is base64url JSON naming its format version, its
list (`scope`, such as `profile.businesses`) and the keyset; a cursor that is not one of these,
belongs to another list or does not fit the keyset model is `InvalidCursorError`
(`pagination-cursor-invalid`, 422). Cursors are opaque but not signed: a crafted one only moves
where a page starts inside rows the caller may read anyway. `encode_cursor` refuses a cursor
longer than 512 characters, so key a list on short values (the profile's business list keeps
only the last id in its cursor and reads the name again).

## Idempotency keys

A route that creates something declares `key: IdempotencyKey` and returns
`run_idempotent(store, tenant, key, 201, produce)`. The header `Idempotency-Key` holds 8 to 128
printable characters, such as a UUID; without it the route answers 428
(`idempotency-key-required`). The first request with a key claims it and runs `produce`; the 2xx
or 4xx it returns is recorded and replayed, with `Idempotent-Replayed: true`, to every retry with
the same key, method, path and body for 24 hours after it was recorded. The same key with another
request is a 422 (`idempotency-key-reused`), and a retry while the first request still runs is a
409 (`idempotency-request-in-flight`, with `Retry-After: 1`). A 5xx is never recorded, and an
exception from `produce` releases the key, so the retry runs again; a request that dies without
recording anything frees its key after 5 minutes. Keys belong to a tenant. The route adds
`responses=IDEMPOTENCY_RESPONSES` so the spec lists the 409, 422 and 428.

The service's migration calls `create_idempotency_table(op)`: the `idempotency_key` table with
the forced tenant policy and a second, permissive policy that lets anyone delete rows whose
`expires_at` has passed, which the migration lint accepts. `SqlAlchemyIdempotencyStore(engine)`
runs each key statement in its own short transaction; `store.recorder(connection)` runs them in
the caller's transaction instead, so the key row commits with the business write or rolls back
with it. `MemoryIdempotencyStore` serves tests and memory mode. `python -m py_common.idempotency
purge`, with the service's `CW_DATABASE_URL`, deletes the expired keys of every tenant and is
meant to run once a day; it exits 1 when the schema has no `idempotency_key` table. The package's
`__init__` imports neither FastAPI nor SQLAlchemy, so `py_common.problems` can map its errors.

## Feature flags

`py_common.flags` reads the flag registry (`packages/flags/registry.json`, through the copy
`make flags` writes) with OpenFeature. A service calls `configure_flags(settings)` once at
start-up; `flag_enabled("qa.kag", tenant_id)` answers a bool flag and `flag_value(name)` a
string flag, and a name the registry does not hold raises `UnknownFlagError`. With
`CW_FLAGS_PROVIDER=env` (the default) a flag's value comes from the variable the code already
reads, else `CW_FLAG_<NAME>` (dots as underscores, so `CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL`),
else the registry default; a tenant-targeted flag that is on narrows to the tenant ids in its
allow-list (`CW_FLAG_<NAME>__TENANTS`, or the variable the code already reads, such as
`CW_QA_KAG_TENANTS`). The variables come from the environment over the `.env` files the
settings read (`settings.env_files`), so settings built with `_env_file=None`, as the tests, the
demo and the evals build them, read no `.env` for their flags either. With
`CW_FLAGS_PROVIDER=unleash` the flags come from an Unleash server
at `CW_UNLEASH_URL` with the client token `CW_UNLEASH_API_TOKEN`, under their registry names;
the tenant id is Unleash's `userId` and the `tenantId` property. That provider needs the
optional extra `py-common[unleash]`, so a service that calls `configure_flags` depends on
`"py-common[unleash]"` in its own `pyproject.toml`, as the profile service does. Its image is
built with `--no-dev`, and without the extra it would not start with `CW_FLAGS_PROVIDER=unleash`.
A malformed value or a flag Unleash does not hold answers the registry default, which is off,
and logs `flag_evaluation_failed`.

## Telemetry

`create_app` calls `configure_telemetry`: with `CW_OTEL_ENDPOINT` set (the dev stack's
collector is `http://localhost:4317` under `make dev-observability`) a tracer and a meter
provider export over OTLP gRPC, the FastAPI instrumentation adds a span and the HTTP duration
metric per request (`/health` and `/ready` excluded), and the exporters flush when the app
shuts down. With the endpoint empty nothing is installed and every span and metric is a no-op.
Workers call `configure_telemetry` themselves and `telemetry.shutdown()` on exit. A service
with a SQLAlchemy engine calls `instrument_engine(engine, telemetry)` for a span per statement.
Log lines inside a recording span carry `trace_id` and `span_id`. The HTTP instrumentation
emits the stable semantic conventions (`http.server.request.duration` in seconds,
`http.route`, `http.response.status_code`), which the Grafana dashboard queries.

## Temporal

`py_common.temporal.connect(settings)` returns a client with the pydantic data converter and
the OpenTelemetry tracing interceptor (spans are created even when the starter carried none).
An activity is a class:

```python
class FetchDocument(ActivityBase[Discovered, Fetched]):
    name = "pipeline.fetch_document"
    input_type, output_type = Discovered, Fetched
    start_to_close = timedelta(minutes=5)
    retry_policy = RetryPolicy(
        maximum_attempts=5, non_retryable_error_types=["InvariantViolationError"]
    )

    async def run(self, input: Discovered) -> Fetched: ...
```

`validate` runs before `run`, `record` after it (a failure there is logged, not raised), and
`self.heartbeat()` is a no-op outside Temporal so unit tests call `run` directly or through
`temporalio.testing.ActivityEnvironment`. A workflow calls `FetchDocument.schedule(input)`,
which applies the class's timeouts and retry policy. A worker registers instances:
`run_worker(settings, WorkerConfig(task_queue="pipeline"), workflows=[...],
activities=[FetchDocument(adapter), ...])`; it stops on SIGTERM or SIGINT. The time-skipping
test server is x86-only; tests use `WorkflowEnvironment.start_local()` (the Temporal CLI dev
server) instead. `services/pipeline` has the sample workflow.

While a worker runs, its queue reports `temporal_worker_up{task_queue} = 1` through one
observable gauge per process, and the series ends when the worker stops or fails.
`run_worker` does this with `liveness.running(task_queue)`; a process that builds its own
workers wraps each one in it, so several queues in one process share the instrument. With no
`CW_OTEL_ENDPOINT` the gauge records nothing. `py_common.temporal` takes its meter from
`opentelemetry.metrics.get_meter` and never imports `py_common.telemetry`, the outbox, FastAPI
or SQLAlchemy, because workflow and activity modules import it (an import-linter contract).

## Events and the outbox

An event is a kernel `DomainEvent` subclass with a `topic` and a `schema_version` that match a
schema in `packages/contracts/events`. `py_common.events.to_message` turns it into the envelope
(`EventMessage`), `encode`/`decode` are the bytes on the bus, and `payload_of` converts the
event's own fields (typed ids, dates, decimals, enums, nested dataclasses, tuples) into JSON.

Producing (ADR-005): a service migration calls `create_outbox_table(op)` once; the use case
then calls `OutboxWriter().write(connection, event)` on the connection that holds its state
change, so the row commits or rolls back with it. `partition_key` is the Kafka key (the tenant by
default for tenant events; pass the aggregate id for regulatory events). A relay process per
service schema, `make relay SERVICE=<name>` locally, publishes pending rows, retries with
exponential backoff and moves a message to `<topic>.dlq` after eight failures
(`docs/runbooks/outbox-relay.md`). The relay installs telemetry as `outbox-relay`: with
`CW_OTEL_ENDPOINT` set it exports its counters by topic and the `outbox_relay_pending` gauge by
`db_schema` every 15 seconds, which the `OutboxBacklog` alert reads.

Consuming: a migration calls `create_processed_event_table(op)`; the service runs
`IdempotentConsumer(group_id=..., store=PostgresProcessedStore(engine, group_id=...),
handler=..., producer=...)`. The handler receives the decoded `EventMessage` and the unit of
work, whose `connection` is the transaction that also records the event id, so a redelivery is
skipped and a handler crash rolls everything back. After three failed attempts the message goes
to `<topic>.<group>.dlq` and the offset is committed. `py_common.outbox.testing` has the fakes
service tests use instead of a broker.

A service whose repositories are synchronous consumes through `py_common.outbox.sync` instead:
`SyncProcessedStore(engine, group_id=...)` on a sync engine gives each unit of work its own
connection and its own thread, and `sync_handler(fn)` runs `fn(message, connection)` there, in the
transaction that also records the event id. The handler's writes, the outbox rows it writes with
`OutboxWriter` and the `processed_event` row commit together or roll back together, and a
handler that calls another service over HTTP blocks its unit's thread, never the event loop.
`run_consumer(settings, group_id=..., topics=..., handler=..., stop=...)` runs one group against
`CW_DATABASE_URL` and `CW_KAFKA_BOOTSTRAP` until `stop` is set. Group ids are
`<service>.<purpose>`, such as `notification.obligations`, so dead letters land in
`<topic>.notification.obligations.dlq`. The store works on any SQLAlchemy engine, so handler
tests can run it on a SQLite file.

## Worker processes

A service with background work exposes `<pkg>.worker.components(settings)`, which returns
`py_common.runtime.WorkerComponents`: `consumers` (`ConsumerComponent(group_id, topics,
handler)`, run with `run_consumer`), `relays` (`RelayComponent()`, the outbox relay of the
service schema), `periodic` (`PeriodicComponent(name, fn, interval_seconds=...)`, or
`next_run=daily_at(time(3, 0, tzinfo=IST))` for a daily job; a sync `fn` runs on a thread and a
failing run is logged and tried again at the next time) and `temporal` (`TaskComponent(name,
run)`, any coroutine that runs until the stop event, such as a Temporal worker). Its
`python -m <pkg>.worker` calls `run_worker_process(settings, components, version=...)`, and
`make worker SERVICE=<svc>` runs that locally. Every component runs until SIGTERM or SIGINT; when
one fails, the others stop and the process exits with the error, for the supervisor to restart
it. Components add up (`a + b`), so one process can host several services' work.

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

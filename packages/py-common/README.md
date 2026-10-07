# py-common package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing and metrics (OpenTelemetry), config, auth middleware, problem details, cursor pagination, idempotency keys, feature flags, outbox, the audit log writer, Temporal worker scaffold, testing fakes
- **Owning team:** Platform and Infrastructure
- **Consumes:** n/a
- **Emits / publishes:** Golden-path library consumed by every Python service

## Layout

```
src/py_common/
  settings.py          # pydantic-settings, env_prefix CW_, env_file .env; with_search_path(url, schema)
  kafka.py             # KafkaClientConfig: bootstrap servers, SASL/SCRAM and TLS for every Kafka client
  flags.py             # configure_flags, flag_enabled, flag_value: OpenFeature over the flag registry (env or Unleash)
  flags_registry.json  # generated from packages/flags/registry.json by make flags; never edited by hand
  logging.py           # structlog JSON logging bridging stdlib records; correlation_id/tenant_id/actor contextvars
                       # and personal identifiers masked on every line (redact_pii)
  health.py            # GET /health and GET /ready router with pluggable readiness checks
  request_context.py   # x-request-id middleware; correlation_id_of(request) for handlers and dependencies
  problems.py          # RFC 9457 problem+json handlers, Problem schema, problem_responses() for routers
  pagination.py        # keyset pagination: Pagination (limit, cursor), encode/decode_cursor, Page[T], page_of
  app.py               # create_app(service_name, version, routers, problem_status, authenticator, ...); module_app for lazy main modules
  database.py          # create_pooled_engine: QueuePool sized by CW_DB_POOL_SIZE and CW_DB_MAX_OVERFLOW, pinged before use
  db_roles.py          # the services' roles cw_<schema> (infra/dev/postgres/roles.sql): apply_roles, as_role for integration tests
  auth/                # verified identities; the package itself loads no FastAPI
    keys.py            # ES256 SigningKey, KeySet (first signs, all published), load_signing_keys
    tokens.py          # TokenIssuer, TokenVerifier (ES256 only), JwksUrlSource (1 h cache), StaticKeySource
    errors.py          # 401 token required, 401 token invalid, 403 forbidden, 403 tenant mismatch, 503 keys unavailable
    context.py         # current_principal, bind_principal: actor and tenant_id in the log context
    fastapi.py         # Authenticator by CW_AUTH_MODE, authenticate, tenant_scope, require_roles, shared_token_or_roles
    service_tokens.py  # ServiceTokenSource (cached until a minute before expiry), IssuerTokenSource (in process), BearerAuth, service_auth_from
    testing.py         # TestIssuer: tokens signed with a key generated at run time; bearer(token)
  telemetry.py         # configure_telemetry (OTLP gRPC or HTTP to CW_OTEL_ENDPOINT, with CW_OTEL_HEADERS), instrument_app, instrument_engine
  temporal/
    client.py          # connect(settings): pydantic converter + tracing interceptor; API key or mTLS for Temporal Cloud
    activity.py        # ActivityBase: validate/run/record, retry policy and timeouts on the class, schedule()
    worker.py          # WorkerConfig, build_worker, run_worker (stops on SIGTERM/SIGINT)
    liveness.py        # running(task_queue): the temporal_worker_up{task_queue} gauge while a worker runs
  events.py            # EventMessage (the envelope), to_message/encode/decode, payload_of(event)
  migrations.py        # alembic helpers: enable_tenant_rls, create_append_only_guard and their drop twins
  runtime.py           # WorkerComponents (consumers, relays, periodic jobs, Temporal workers, tasks, hooks); ComponentRegistry; run_worker_process
  outbox/
    schema.py          # outbox_event and processed_event tables; create_*/drop_* helpers for alembic
    writer.py          # OutboxWriter.write(connection, event): the row commits with the state change
    store.py           # store protocols; PostgresOutboxStore (FOR UPDATE SKIP LOCKED), PostgresProcessedStore
    producer.py        # MessageProducer protocol; AiokafkaProducer (idempotent, acks=all)
    relay.py           # OutboxRelay: publish, retry with backoff, dead-letter; python -m py_common.outbox
    consumer.py        # IdempotentConsumer: once per event id and consumer group, consumer dead-letter topic
    sync.py            # SyncProcessedStore and sync_handler: sync handlers in the unit's transaction; run_consumer
    admin.py           # OutboxAdmin: the dead rows, one row, a dead row back to pending (admin routes)
    replay.py          # DeadLetters: list a dead-letter topic, send a message back; python -m py_common.outbox.replay
    testing.py         # FakeProducer, FakeConsumer, MemoryOutboxStore, MemoryProcessedStore for service tests
  idempotency/         # Idempotency-Key with 24 hour replay; the package itself loads no FastAPI or SQLAlchemy
    store.py           # fingerprint, the begin outcomes, IdempotencyStore and IdempotencyRecorder protocols
    memory.py          # MemoryIdempotencyStore
    sqlalchemy.py      # SqlAlchemyIdempotencyStore (own transactions); SqlAlchemyIdempotencyRecorder (the caller's)
    schema.py          # idempotency_key: create/drop_idempotency_table(op), forced tenant policy, purge policy
    fastapi.py         # IdempotencyKey dependency, run_idempotent, IDEMPOTENCY_RESPONSES
    errors.py          # 428 key required, 422 key reused, 409 request in flight
    purge.py           # purge_expired_keys(settings) and purge_job(settings): the daily purge as a worker component
    __main__.py        # python -m py_common.idempotency purge
  audit/               # the audit log, audit.event; the package itself loads no SQLAlchemy
    context.py         # audit_actor(service, principal), current_correlation_id()
    memory.py          # MemoryAuditSink: the memory stores' twin, refusing what the table refuses
    schema.py          # audit.event; create/drop_audit_table(op), create/drop_audit_read_policies(op)
    writer.py          # AuditWriter.write(connection, entry); PostgresAuditSink; entry_from_row
    testing.py         # audit_entry, install_audit_table, read_audit_entries
tests/unit/
tests/integration/     # the outbox against Postgres and Redpanda, the migration helpers, idempotency keys and the audit table on Postgres, flags on an Unleash server (testcontainers)
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
- `token`: every route that reads the caller (tenant, service-to-service, analyst and admin
  routes) needs a bearer token. `CW_ENV=prod` refuses any other mode.

A route reads the caller when it depends on one of the dependencies below; one that does not
stays open in every mode. The routes open in `token` mode, all by design:

- every service's `/health`, `/ready` and `/v1/<service>/ping`;
- identity's sign-in and keys: `POST /v1/identity/sessions`, `POST /v1/identity/tenants`,
  `POST /v1/identity/service-tokens`, `GET /v1/identity/.well-known/jwks.json` and
  `POST /v1/identity/dev/provider-tokens` (fake provider, local and test only); the price list
  `GET /v1/identity/billing/plans`; and `POST /v1/identity/billing/webhook`, which checks the
  billing provider's signature instead;
- profile's `GET /v1/ontology`;
- notification's `GET /v1/notification/templates`, and `POST /v1/notification/receipts/email`,
  which checks SNS's basic credentials instead;
- the rulebook's read API, the same for every tenant: rule versions and their citations, rules,
  documents, entities, relations, clauses and `POST /v1/rulebook/search`. Its review queues
  (`GET /v1/rulebook/review/...`) need an analyst, reviewer or admin.

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
and is shared by the clients built from the same settings. When the called service refuses the
token itself (401 with an `invalid_token` challenge or the `auth-token-invalid` problem type) it is
dropped and the request resent once with a fresh one; any other 401, such as a wrong shared secret
or a missing tenant, comes back as it came. When identity cannot be reached or refuses the
client, the cached token stays in use until it expires and the next attempt waits 5 seconds;
with no valid token the call fails at once with `service-token-unavailable` (503).

A process that hosts the identity service next to the services that call each other needs no
client secrets for those calls: `IssuerTokenSource(issuer, Principal.service(client_id, scopes))`
mints the service's token with identity's own `TokenIssuer` in the process and keeps it the same
way, and `service_auth_from(settings, token_source=source)` puts it on the service's clients
whatever the settings say.

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

## Logging

`configure_logging(service_name=..., env=settings.env)`, which `create_app` and every worker call,
renders structlog events and stdlib records (uvicorn, httpx, sqlalchemy) through one processor
chain as JSON lines with `timestamp`, `level`, `logger`, `event`, `service`, `correlation_id`,
`tenant_id` and `actor`, plus `trace_id` and `span_id` inside a span (`CW_LOG_JSON=false` prints
them for a terminal instead; `cw-mvp check-config` refuses it in staging and production).

The last processor, `redact_pii`, masks personal identifiers on every line, always, with no
setting to turn it off: GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses become
`[GSTIN]`, `[PAN]`, `[AADHAAR]`, `[PHONE]` and `[EMAIL]` (`domain_kernel.pii.mask_pii_in`). It
masks the event text, every other value at any depth (inside dicts, lists and tuples) and, in
JSON output, the exception. A value that is not text, a number, a boolean or None (an exception,
a pydantic model, a dataclass, a set, bytes) is masked as its `repr`, which is what the JSON
renderer would print. What the caller logged is copied, never changed. It leaves alone, at the
top of the line only, the fields listed above; the value of any key ending in `_id` or `_ids` at
any depth; and, wherever they stand (a request path, a workflow id, the event text), every UUID
in its canonical form and every lower-case hex id of 16 or more with a letter in it (a SHA-256
digest, a `uuid4().hex`, a span id), with no letter or digit next to it. Their digit runs would
otherwise read as Aadhaar or phone numbers in about one UUID in 70, one digest in 31, one
`.hex` in 61 and one span id in 152. Inside the exception nothing is left alone.

The log line takes identifiers in more shapes than a prompt does, since URLs, keys and file names
carry them. Each shape was checked against the repository's regulatory texts (the recorded
notifications and listings, the golden sets, the seed calendar's quotes), where it masks nothing
the prompt patterns leave, and is taken:

- an email address URL-encoded, as in a query string: `owner%40example.com`;
- an identifier glued to an underscore or to digits: `pan_ABCDE1234F`, `gstin_29ABCDE1234F1Z5`,
  `ABCDE1234F09876543210`, `owner@example.com_old`;
- a PAN or GSTIN in lower case (all of it; mixed case is left);
- `+91 (987) 654 3210` (three, three and four digits behind a prefix) and `00919876543210`.

Masking is idempotent (a second pass changes nothing) and linear in time: 64 KB of `a.a.a.…@` in
a request path takes about 2 ms to mask, where it took 2.2 s and blocked the event loop.

`redact_pii` never raises into the code that logs. A value it cannot mask (a `repr` that raises,
say) turns the line into `log_redaction_failed`, with the fields above, the masked event text and
the error's type; a value inside itself, or nested deeper than 32 levels, is cut there with
`[CYCLE]` or `[TOO DEEP]`.

A JSON traceback carries the locals of its frames only with `CW_ENV` local or test. Anywhere else
it carries none, so a request body, a token or a secret held in a local never reaches the log
collector. Where they are carried, each local is cut to 80 characters before it is masked, so an
identifier cut in two may show in part on a developer's machine.

By design, any other ten-digit number that starts with 6 to 9, and any twelve-digit number that
starts with 2 to 9, is masked as a phone or an Aadhaar number, whatever it is: an amount or a
reference. Log such an id under a key ending in `_id`, and a number as an int, to keep it whole.
Masking is pattern matching, so a name, an address or free text is not masked. The console
renderer formats a traceback itself, after the chain, so a traceback printed with
`CW_LOG_JSON=false` is not masked. OpenTelemetry spans are not masked either.

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

A managed collector is reached the way it asks: `CW_OTEL_PROTOCOL=http/protobuf` sends traces to
`<endpoint>/v1/traces` and metrics to `<endpoint>/v1/metrics` (Grafana Cloud's OTLP gateway, for
example), and `CW_OTEL_HEADERS` holds the headers every export carries, in the
`OTEL_EXPORTER_OTLP_HEADERS` form `Authorization=Basic%20<token>,key2=value2` (URL-encoded
values). The default is gRPC to the endpoint itself with no headers, the dev stack's collector.
`Telemetry.shutdown()` flushes once; later calls do nothing, so every app of a process that
hosts several can call it from its lifespan.

## Temporal

`py_common.temporal.connect(settings)` returns a client with the pydantic data converter and
the OpenTelemetry tracing interceptor (spans are created even when the starter carried none).
It connects in plain text to the dev stack's server. For Temporal Cloud it sends
`CW_TEMPORAL_API_KEY` over TLS, or presents the client certificate `CW_TEMPORAL_TLS_CERT` with
its key `CW_TEMPORAL_TLS_KEY` (PEM text, so they fit a secret store) for mutual TLS; the settings
refuse both at once and a certificate without its key. `CW_TEMPORAL_TLS` turns TLS on or off
explicitly; left empty it is on whenever a credential is set.
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
(`docs/runbooks/outbox-relay.md`); the row is then `dead`, and keeps when it went dead in
`available_at`. The relay installs telemetry as `outbox-relay`: with `CW_OTEL_ENDPOINT` set it
exports its counters by topic and the `outbox_relay_pending` gauge by `db_schema` every 15
seconds, which the `OutboxBacklog` alert reads.

Dead rows and dead letters: `py_common.outbox.admin.OutboxAdmin(connection)` lists a schema's
dead rows (the newest dead first, a page at a time), reads one, and puts a dead row back to
`pending` with its attempts reset, inside the caller's transaction, so an admin route commits it
with its audit row (the pipeline's `GET /v1/pipeline/outbox/dead` and
`POST /v1/pipeline/outbox/{event_id}/requeue` do). `py_common.outbox.replay.DeadLetters` lists a
dead-letter topic, the relay's `<topic>.dlq` or a consumer's `<topic>.<group>.dlq`, read only (no
consumer group, nothing committed; a read that does not reach the end of every partition in
time is a `TimeoutError`, never a part of the topic), and sends one message, by its event id,
back to its origin topic without the dead-letter headers, once the broker says it has that topic;
`make replay` is its command line (exit 0 done, 1 unknown, 2 the broker did not answer or the
read timed out, 64 wrong arguments). `MemoryOutboxStore`
answers the same three as `OutboxAdmin`, and `FakeConsumer` reads what a `FakeProducer` sent.

Every Kafka client (the relay's producer, consumers, their dead-letter producers and the topic
tooling) connects through `py_common.kafka.KafkaClientConfig.from_settings(settings)`, whose
`aiokafka_kwargs()` carry `CW_KAFKA_BOOTSTRAP` and the security settings: the dev stack's
`PLAINTEXT` by default, or `CW_KAFKA_SECURITY_PROTOCOL=SASL_SSL` with
`CW_KAFKA_SASL_MECHANISM` (`SCRAM-SHA-256` or `SCRAM-SHA-512`), `CW_KAFKA_SASL_USERNAME` and
`CW_KAFKA_SASL_PASSWORD` for a managed cluster, verified against `CW_KAFKA_SSL_CAFILE` or the
system's certificate authorities. The settings refuse a SASL protocol without all three.
`AiokafkaProducer` takes the config or a bare bootstrap string, `IdempotentConsumer.run` takes
`kafka=`, and `relay.run(settings, stop=...)` leaves signal handling to a caller that passes its
own stop event.

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

## Audit log

Every admin action, and every change an internal tool makes to customer data, writes one row to
`audit.event` (guide sections 9, 15 and 16): the action as a dotted name
(`applicability.review.resolve`), the tenant whose data it touched or none for a platform-wide
action, the subject's type and id, the actor, the reason, the state before and after as JSON, the
time and the correlation id. The row is the kernel's `AuditEntry` (`domain_kernel.audit`). A unit
of work exposes an `audit` sink and the use case writes the entry there, in the transaction of the
action, so the row commits or rolls back with it: `PostgresAuditSink(connection)` inserts with
`AuditWriter.write(connection, entry)` as `OutboxWriter` does for events, and
`MemoryAuditSink(log, tenant_id=...)` serves memory stores, committing with the unit and refusing
what the table refuses.

- `audit_actor(service, principal)` names the actor: the user a verified token names, labelled
  with the roles they hold (never a name), or the service client; anyone else (the anonymous
  principal of `header` mode, or work no request started) is the system, `system:<service>`.
  `current_correlation_id()` is the request's correlation id as `RequestContextMiddleware` bound
  it. `py_common.audit` loads no web or database framework (an import-linter contract), so an
  application layer may call both.
- Identity's migration owns the table (`py_common.audit.schema.create_audit_table(op)`): the schema
  `audit` when it is missing, indexes on (tenant_id, occurred_at) and (action, occurred_at),
  forced row-level security that lets a session read and write its tenant's rows and add rows of
  no tenant, and a trigger that refuses UPDATE and DELETE, a tenant's erasure included. Its
  migration 0006 adds the read scopes (`create_audit_read_policies(op)`), two FOR SELECT policies
  on the setting `app.audit_scope`: `regulatory` reads the rows of no tenant, `export` reads every
  row. Only identity sets it, after its own role checks.
- `py_common.audit.testing` has `audit_entry(...)`, `install_audit_table(connection)` for a
  service's integration tests and `read_audit_entries(connection)`.
- The log keeps an entry masked for personal identifiers (`py_common.audit.masked_entry`), with
  the patterns the log lines are masked with (`domain_kernel.pii.mask_pii_in`): GSTINs, PANs,
  Aadhaar numbers, phone numbers and email addresses in the reason, and in every text of `before`
  and `after` at any depth, become `[GSTIN]`, `[PAN]`, `[AADHAAR]`, `[PHONE]` and `[EMAIL]`. As on
  a log line, a UUID in its canonical form and a lower-case hex id of 16 or more (a SHA-256 digest)
  are kept whole wherever they stand (a reviewer's user id under `resolved_by`, a transcript's
  digest), and the value of a key ending in `_id` or `_ids` is left alone. The action, the subject
  and its id, the actor and the correlation id are never masked. `AuditWriter` and the memory twin
  both store the masked entry, so a service's tests on its memory store see what the table would
  hold. A reason that masking makes longer than 2,000 characters is cut. A use case still keeps
  personal data out of an entry where it can: masking is pattern matching, it misses names and
  free text, and it masks any ten-digit number from 6 to 9 and any twelve-digit one from 2 to 9
  outside an id key. A masked row cannot show what a PAN, GSTIN, email or phone number changed
  from or to.

Each service's database role (`infra/dev/postgres/roles.sql`, `cw_<schema>`) may only insert
into the table, and only `cw_identity` may also read it; the writer needs nothing more, since it
inserts without `RETURNING`. The MVP image's one role, `cw_app`, holds SELECT on `audit` as well,
so under it the read scopes are a code convention rather than a role boundary
([docs/runbooks/audit-export.md](../../docs/runbooks/audit-export.md)).

Identity reads the log (`GET /v1/identity/audit`, `identity-admin audit-export`; the identity
README and [docs/runbooks/audit-export.md](../../docs/runbooks/audit-export.md) describe both).
A tenant's erasure leaves its audit rows as they are: they were masked when written and are kept
seven years, the data map's documented exception (docs/legal/data-map.md).

## Tenant erasure

`py_common.erasure` is the common part of the erasure consumers (docs/runbooks/data-requests.md):

- `erasure_component(service, eraser_on, enabled=..., verifier=...)` is the consumer of
  `tenant.deletion.requested` in group `<service>.erasure` a service's worker hosts, in two steps
  (`read_then_write`, on `read_first_store`). With no transaction open: while `enabled(tenant)`
  answers false it only logs `erasure.off`; otherwise it asks identity what it holds of the
  tenant's deletion (`HttpErasureVerifier`, `GET /v1/identity/erasures/{tenant_id}` with the
  service's token, scope `erasure:verify`, within 5 s; `verifier_from(settings)`). On the
  consumer's connection: an event identity did not send for the tenant's open deletion request,
  or one for the internal tenant (`domain_kernel.erasure.erasure_refusal`), writes a
  `tenant.erasure_refused` audit row and raises `ErasureRefusedError`, which the consumer
  dead-letters at once (`EventRefusedError`, `Outcome.REFUSED`); otherwise
  `eraser_on(connection)` makes the service's `TenantEraser`, which erases and then records
  `tenant.data.erased` in the service's outbox, its `tenant.erased` row in `audit.event` and its
  erased marker, all committing with the `processed_event` row (`erase_and_record`). Identity
  unreachable (`IdentityUnreachableError`) is retried, then dead-lettered; nothing is erased.
- `erasure_switch(settings)` is the process's one `ErasureSwitch`, which answers `enabled` from
  the flag `identity.tenant_erasure` per tenant. The process's flags are configured once
  (`configure_flags_once`), however many services a worker hosts.
- The erased marker: `erased_tenant` (tenant_id, erased_at, deletion_event_id) in each service's
  schema, made by `create_erased_tenant_table(op)`, with no row-level security since every
  session must see it (the lint exemption `*.erased_tenant`). `PostgresTenantEraser.record`
  writes it (`mark_erased`). `PostgresErasedTenants(engine)` is what `create_app(erased_tenants=...)`
  takes: `tenant_scope` then answers 410 `tenant-erased` for a tenant it holds.
  `skip_erased(service, handler)` and `skip_erased_write(service, write)` wrap a consumer's
  handler: an event of an erased tenant is marked processed with the outcome `erased_tenant`,
  and nothing is written. The check holds a shared advisory lock on the tenant's erasure for the
  rest of the consumer's transaction, and `begin_erasure` takes it exclusively, so a handler
  either commits before the erasure starts or sees the marker. `MemoryErasedTenants` is the
  memory stores' twin.
- A Postgres eraser subclasses `PostgresTenantEraser` (the recording half) and builds on
  `begin_erasure` (the erasure lock, then `app.tenant_id` and `app.erasure` for the
  transaction), `delete_rows`, `count_rows` and `prune_outbox` (the tenant's published or dead
  outbox rows; `OUTBOX_RETAINED` names the pending ones it keeps: nothing prunes the outbox on its
  own, see docs/runbooks/outbox-relay.md). `ERASED_RETAINED` names the marker every eraser keeps.
  Their statements are SQLAlchemy Core: the table and its tenant column come from the eraser's
  fixed list (plain names, which the dialect quotes) and the tenant is a bound parameter. Only the
  advisory locks and `set_config` are SQL text, fixed strings with bound parameters; `make sast`
  refuses SQL assembled into `text()`.
- `py_common.erasure_testing` has `FakeIdentity`, the check a consumer's verifier answers in a
  test, and `assert_nothing_left(connection, schema, tenant, answer)`, the catalog's check each
  service's Postgres erasure test runs: every table of the schema with a column `tenant_id` or
  `*_tenant_id` is one the eraser erased or retained with a reason, and holds no row of the
  tenant unless retained. `tenant_rows` counts them in a Core statement: the catalog's names,
  quoted by the dialect, and the tenant bound.

## Worker processes

A service with background work exposes `<pkg>.worker.components(settings)`, which returns
`py_common.runtime.WorkerComponents`:

- `consumers`: `ConsumerComponent(group_id, topics, handler)`, run with `run_consumer` on a
  `SyncProcessedStore` (`store_factory=` replaces it);
- `relays`: `RelayComponent()`, the outbox relay of the service schema;
- `periodic`: `PeriodicComponent(name, fn, interval_seconds=...)`, or
  `next_run=daily_at(time(3, 0, tzinfo=IST))` for a daily job; a sync `fn` runs on a thread and a
  failing run is logged and tried again at the next time. `py_common.idempotency.purge.purge_job`
  is the daily purge of expired idempotency keys;
- `temporal`: `TemporalComponent(WorkerConfig(task_queue), workflows, activities)`; the Temporal
  workers of a process run on one client through `run_temporal`, each inside
  `liveness.running(task_queue)`;
- `tasks`: `TaskComponent(name, run)`, any coroutine that runs until the stop event;
- `startup` and `shutdown`: `LifecycleHook(name, fn)`. Startup hooks run in order before
  anything starts (a failing one ends the process); shutdown hooks run in reverse once everything
  has stopped, however it stopped, and a failing one is logged.

Its `python -m <pkg>.worker` calls `run_worker_process(settings, components, version=...)`, and
`make worker SERVICE=<svc>` runs that locally. Every component runs until SIGTERM or SIGINT; when
one fails, the others stop and the process exits with the error, for the supervisor to restart
it. Components of one service add up (`a + b`). A process that hosts several services registers
each one's components with the settings they run on,
`ComponentRegistry().register("profile", profile_settings, components)`, and runs them with
`run_registry(registry, stop)`: each consumer, relay and job reads its own service's database
schema, consumer groups and task queues must be unique across the services, and the Temporal
workers share one client. Every consumer, relay, periodic job and task reports
`worker_loop_up{loop="<service>/<component>"}` while it runs; Temporal workers report
`temporal_worker_up{task_queue}` instead.

## Several services in one process

The pieces a composition root needs to host several services' apps in one process:

- each service's `main` module exposes `build_app(settings=None, ...)` and serves `app` lazily
  through `module_app(name, build_app)` in a module `__getattr__`, so importing a service builds
  nothing and reads no environment, while `uvicorn <pkg>.main:app` and `make openapi` still work;
- `create_app` keeps its readiness checks on `app.state.readiness_checks`, for an outer `/ready`;
- `RequestContextMiddleware` reuses a correlation id an outer copy of itself put in
  `scope["state"]` and adds `x-request-id` to a response only once;
- a bound `service` log context variable wins over the configured service name, so each request
  logs as the service that served it;
- `problem_response(request, ...)` answers with a problem from plain ASGI code;
- `Telemetry.shutdown()` is safe to call from every app's lifespan;
- `create_pooled_engine(settings)` gives each engine a small pool (`CW_DB_POOL_SIZE`, default
  3, and `CW_DB_MAX_OVERFLOW`, default 2), and `max_connections(settings)` is what one engine may
  hold, to add up against the database's limit;
- `IssuerTokenSource` and `service_auth_from(settings, token_source=...)` carry service tokens
  without client secrets.

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

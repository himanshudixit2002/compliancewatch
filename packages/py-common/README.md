# py-common package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing and metrics (OpenTelemetry), config, auth middleware, problem details, outbox, Temporal worker scaffold, testing fakes
- **Owning team:** Platform and Infrastructure
- **Consumes:** n/a
- **Emits / publishes:** Golden-path library consumed by every Python service

## Layout

```
src/py_common/
  settings.py          # pydantic-settings, env_prefix CW_, env_file .env
  logging.py           # structlog JSON logging bridging stdlib records; correlation_id/tenant_id contextvars
  health.py            # GET /health and GET /ready router with pluggable readiness checks
  request_context.py   # x-request-id middleware; correlation_id_of(request) for handlers and dependencies
  problems.py          # RFC 9457 problem+json handlers, Problem schema, problem_responses() for routers
  app.py               # create_app(service_name, version, routers, problem_status, ...)
  telemetry.py         # configure_telemetry (OTLP to CW_OTEL_ENDPOINT), instrument_app, instrument_engine
  temporal/
    client.py          # connect(settings): pydantic converter + tracing interceptor
    activity.py        # ActivityBase: validate/run/record, retry policy and timeouts on the class, schedule()
    worker.py          # WorkerConfig, build_worker, run_worker (stops on SIGTERM/SIGINT)
    liveness.py        # running(task_queue): the temporal_worker_up{task_queue} gauge while a worker runs
  events.py            # EventMessage (the envelope), to_message/encode/decode, payload_of(event)
  migrations.py        # alembic helpers: enable_tenant_rls, create_append_only_guard and their drop twins
  outbox/
    schema.py          # outbox_event and processed_event tables; create_*/drop_* helpers for alembic
    writer.py          # OutboxWriter.write(connection, event): the row commits with the state change
    store.py           # store protocols; PostgresOutboxStore (FOR UPDATE SKIP LOCKED), PostgresProcessedStore
    producer.py        # MessageProducer protocol; AiokafkaProducer (idempotent, acks=all)
    relay.py           # OutboxRelay: publish, retry with backoff, dead-letter; python -m py_common.outbox
    consumer.py        # IdempotentConsumer: once per event id and consumer group, consumer dead-letter topic
    testing.py         # FakeProducer, MemoryOutboxStore, MemoryProcessedStore for service tests
tests/unit/
tests/integration/     # the outbox against Postgres and Redpanda, the migration helpers on Postgres (testcontainers)
```

## Problem details

Every error a service returns is `application/problem+json` (RFC 9457) with `type`, `title`,
`status`, `detail`, `instance` and `correlation_id`. `create_app` installs the handlers for
every app. A `DomainError` maps to the status the service passes in `problem_status`, for
example `{BudgetExceededError: 429}`; the most specific class in the error's MRO wins, the
kernel's defaults (`InvariantViolationError` 422, `UnknownAttributeError` 404) apply
underneath, and an unmapped domain error is a 400. An error class may define
`problem_headers` (a mapping) and those headers are copied onto the response; the gateway's
budget error sets `Retry-After` that way. Request validation errors are 422 with an `errors`
list that does not echo the submitted value, `HTTPException` keeps its status with type
`about:blank`, and an unhandled exception is a generic 500 that is logged with the
correlation id. Routers declare the shape in OpenAPI with
`responses=problem_responses(422, 429)`; the `Problem` schema is published under
`components.schemas` automatically. Two responses every route can give are documented without
a declaration: the 422 of request validation is a `Problem` (FastAPI's default
`HTTPValidationError` entry is replaced), and every operation that takes a body lists a 400
for a body that is not UTF-8, which fails before validation runs.

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

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

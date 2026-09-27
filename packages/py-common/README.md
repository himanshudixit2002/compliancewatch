# py-common package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing (OpenTelemetry), config, auth middleware, problem details, outbox, testing fakes
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
  events.py            # EventMessage (the envelope), to_message/encode/decode, payload_of(event)
  outbox/
    schema.py          # outbox_event and processed_event tables; create_*/drop_* helpers for alembic
    writer.py          # OutboxWriter.write(connection, event): the row commits with the state change
    store.py           # store protocols; PostgresOutboxStore (FOR UPDATE SKIP LOCKED), PostgresProcessedStore
    producer.py        # MessageProducer protocol; AiokafkaProducer (idempotent, acks=all)
    relay.py           # OutboxRelay: publish, retry with backoff, dead-letter; python -m py_common.outbox
    consumer.py        # IdempotentConsumer: once per event id and consumer group, consumer dead-letter topic
    testing.py         # FakeProducer, MemoryOutboxStore, MemoryProcessedStore for service tests
tests/unit/
tests/integration/     # the outbox against Postgres and Redpanda (testcontainers)
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
`components.schemas` automatically.

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
(`docs/runbooks/outbox-relay.md`).

Consuming: a migration calls `create_processed_event_table(op)`; the service runs
`IdempotentConsumer(group_id=..., store=PostgresProcessedStore(engine, group_id=...),
handler=..., producer=...)`. The handler receives the decoded `EventMessage` and the unit of
work, whose `connection` is the transaction that also records the event id, so a redelivery is
skipped and a handler crash rolls everything back. After three failed attempts the message goes
to `<topic>.<group>.dlq` and the offset is committed. `py_common.outbox.testing` has the fakes
service tests use instead of a broker.

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

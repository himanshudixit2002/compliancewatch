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
tests/unit/
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

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

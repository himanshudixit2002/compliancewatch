# py-common package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing (OpenTelemetry), config, auth middleware, outbox, testing fakes
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Golden-path library consumed by every Python service

## Layout

```
src/py_common/
  settings.py   # pydantic-settings, env_prefix CW_, env_file .env
  logging.py    # structlog JSON logging bridging stdlib records; correlation_id/tenant_id contextvars
  health.py     # GET /health and GET /ready router with pluggable readiness checks
  app.py        # create_app(service_name, version, routers, ...) + request-id middleware
tests/unit/
```

## How to run

`uv run pytest packages/py-common` from the repo root; consumed by every service as a workspace dependency (`py-common`).

# py-common package

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 13, 14 and 18.

- **Owns:** Logging, tracing (OpenTelemetry), config, auth middleware, outbox, testing fakes
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Golden-path library consumed by every Python service

## Layout

Flat for now; Python package layout to be added with the uv workspace in Phase 0.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

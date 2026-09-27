# runbooks

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, section 18.

- **Owns:** One runbook per alert, linked from the alert itself (a runbook without a link fails CI)
- **Owning team:** Platform and Infrastructure (each service owner writes the runbooks for their alerts) (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** n/a

## Layout

Flat; one markdown file per alert.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

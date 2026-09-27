# helm

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 14 and 17.

- **Owns:** One chart per service, values per environment (dev, staging, production)
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** The service golden path (Helm chart template)

## Layout

Flat for now; chart template arrives with the service template.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

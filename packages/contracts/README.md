# contracts package

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 7 (event contract rules), 10, 13 and 14.

- **Owns:** OpenAPI specs, event schemas (JSON Schema), generated clients (py + ts), and the event changelog
- **Owning team:** Platform and Infrastructure (custodian); every consuming team reviews a contract change (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Versioned contracts (semver); services pin the versions they consume

## Layout

```
openapi/             # OpenAPI 3.1 specs, public /v1 and internal service APIs
events/              # JSON Schema per event topic (object.verb, past tense) with changelog entries
clients/python/      # generated Python clients
clients/typescript/  # generated TypeScript clients
```

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

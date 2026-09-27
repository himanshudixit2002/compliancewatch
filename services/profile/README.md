# profile service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 6, 7 and 14.

- **Owns:** BusinessProfiles and the Ontology attribute store; validates attributes against the Ontology; versions each change; GSTIN pre-fill. Python package: `profile_service` (the stdlib ships a `profile` module)
- **Owning team:** Core Product (guide section 14)
- **Consumes:** Onboarding UI; GSTIN lookup adapter; partner API
- **Emits / publishes:** profile.updated

## Layout

```
src/profile_service/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters
  main.py          # composition root (to be added by the service template)
migrations/        # alembic
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
pyproject.toml, Dockerfile   # to be added by the service template
```

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

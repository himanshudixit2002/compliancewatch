# identity service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 7, 14 and 16.

- **Owns:** Tenants, users, roles, API keys; maps OIDC claims to roles; issues partner API keys; enforces plan limits
- **Owning team:** Identity and Partner (guide section 14)
- **Consumes:** Keycloak events; admin API
- **Emits / publishes:** tenant.created, user.role.changed

## Layout

```
src/identity/
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

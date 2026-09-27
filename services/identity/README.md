# identity service

Part of the ComplianceWatch monorepo. **Phase 0: service template in place, no domain code yet.**
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
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=identity
make run SERVICE=identity           # http://localhost:8001/health, /ready, /v1/identity/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/identity/Dockerfile -t compliancewatch-identity .
```

Package `identity`, dev port 8001, Postgres schema `identity`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

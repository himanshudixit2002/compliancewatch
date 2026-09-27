# profile service

Part of the ComplianceWatch monorepo. **Phase 0: service template in place, no domain code yet.**
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
make migrate SERVICE=profile
make run SERVICE=profile           # http://localhost:8002/health, /ready, /v1/profile/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/profile/Dockerfile -t compliancewatch-profile .
```

Package `profile_service`, dev port 8002, Postgres schema `profile`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

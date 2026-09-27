# obligation service

Part of the ComplianceWatch monorepo. **Phase 0: service template in place, no domain code yet.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Obligations, evidence metadata, append-only audit log; builds obligations from the RuleVersion template, computes due dates, schedules reminders
- **Owning team:** Core Product (guide section 14)
- **Consumes:** applicability.decided; user actions
- **Emits / publishes:** obligation.created, obligation.due_soon, obligation.closed

## Layout

```
src/obligation/
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
make migrate SERVICE=obligation
make run SERVICE=obligation           # http://localhost:8005/health, /ready, /v1/obligation/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/obligation/Dockerfile -t compliancewatch-obligation .
```

Package `obligation`, dev port 8005, Postgres schema `obligation`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

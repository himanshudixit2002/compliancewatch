# notification service

Part of the ComplianceWatch monorepo. **Service template only: health routes, migrations wiring, no domain code yet.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Notifications, channel adapters (WhatsApp, SES), preferences; dedupe by key, digests, quiet hours, template rendering per channel and language
- **Owning team:** Core Product (guide section 14)
- **Consumes:** obligation.created, obligation.due_soon, digest schedules
- **Emits / publishes:** notification.sent, notification.failed

## Layout

```
src/notification/
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
make migrate SERVICE=notification
make run SERVICE=notification           # http://localhost:8006/health, /ready, /v1/notification/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/notification/Dockerfile -t compliancewatch-notification .
```

Package `notification`, dev port 8006, Postgres schema `notification`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

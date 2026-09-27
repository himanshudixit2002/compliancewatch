# qa service

Part of the ComplianceWatch monorepo. **Service template only: health routes, migrations wiring, no domain code yet.**
Design reference: Project Foundation guide, sections 7, 8 and 14.

- **Owns:** Grounded Q&A sessions: hybrid retrieval filtered by regulator, status=published and as-of date; rerank; answer with citations or refuse
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** Chat UI; WhatsApp replies; rulebook read API; LLM gateway API
- **Emits / publishes:** qa.answered (for evals); qa API

## Layout

```
src/qa/
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
make migrate SERVICE=qa
make run SERVICE=qa           # http://localhost:8007/health, /ready, /v1/qa/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/qa/Dockerfile -t compliancewatch-qa .
```

Package `qa`, dev port 8007, Postgres schema `qa`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

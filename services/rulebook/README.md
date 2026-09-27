# rulebook service

Part of the ComplianceWatch monorepo. **Service template only: health routes, migrations wiring, no domain code yet.**
Design reference: Project Foundation guide, sections 7, 8, 9 and 14.

- **Owns:** Rules, RuleVersions, Clauses, embeddings; versioning, supersession graph, hybrid search index, as-of queries
- **Owning team:** Regulatory Intelligence (guide section 14)
- **Consumes:** rule.published; rulebook read API (served to the engine, Q&A and review service)
- **Emits / publishes:** rule.superseded (scheduled when effective dates pass)

## Layout

```
src/rulebook/
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
make migrate SERVICE=rulebook
make run SERVICE=rulebook           # http://localhost:8003/health, /ready, /v1/rulebook/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/rulebook/Dockerfile -t compliancewatch-rulebook .
```

Package `rulebook`, dev port 8003, Postgres schema `rulebook`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

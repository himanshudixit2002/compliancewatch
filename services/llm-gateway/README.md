# llm-gateway service

Part of the ComplianceWatch monorepo. **Phase 0: service template in place, no domain code yet.**
Design reference: Project Foundation guide, sections 7, 8 and 14.

- **Owns:** Provider routing, prompt registry, semantic cache, cost ledger, PII scrubbing, tracing, per-tenant and per-feature token budgets, circuit breaker per provider
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** All LLM calls from every service
- **Emits / publishes:** llm.call.completed (trace); LLM gateway API

## Layout

```
src/llm_gateway/
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
make migrate SERVICE=llm-gateway
make run SERVICE=llm-gateway           # http://localhost:8008/health, /ready, /v1/llm-gateway/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/llm-gateway/Dockerfile -t compliancewatch-llm-gateway .
```

Package `llm_gateway`, dev port 8008, Postgres schema `llm_gateway`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

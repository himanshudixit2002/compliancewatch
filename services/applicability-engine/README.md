# applicability-engine service

Part of the ComplianceWatch monorepo. **Phase 0: service template in place, no domain code yet.**
Design reference: Project Foundation guide, sections 7, 8, 11 and 14.

- **Owns:** ApplicabilityDecisions: coarse filter by regulator and attribute index, per-business predicate evaluation, LLM-judged free-text predicates with confidence, Temporal fan-out in batches of 1,000
- **Owning team:** Core Product (deterministic path and fan-out); AI Platform owns the LLM evaluator (guide section 14)
- **Consumes:** rule.published (fan-out); profile.updated (single business); rulebook read API; LLM gateway API
- **Emits / publishes:** applicability.decided

## Layout

```
src/applicability_engine/
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
make migrate SERVICE=applicability-engine
make run SERVICE=applicability-engine           # http://localhost:8004/health, /ready, /v1/applicability-engine/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/applicability-engine/Dockerfile -t compliancewatch-applicability-engine .
```

Package `applicability_engine`, dev port 8004, Postgres schema `applicability`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

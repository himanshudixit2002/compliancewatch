# rulebook service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
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

# applicability-engine service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
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

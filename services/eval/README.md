# eval service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 7, 8, 14 and 19.

- **Owns:** Metric runs and drift reports (retrieval recall and precision, grounded rate, citation correctness, extraction acceptance, applicability precision and recall). Golden data lives in `/evals/golden`, the runner in `/evals/harness`. Python package: `eval_service` (`eval` is a builtin)
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** CI; nightly schedule; review edits
- **Emits / publishes:** eval.run.completed; eval thresholds that block merges

## Layout

```
src/eval_service/
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

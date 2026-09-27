# eval service

Part of the ComplianceWatch monorepo. **Service template only: health routes, migrations wiring, no domain code yet.**
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
make migrate SERVICE=eval
make run SERVICE=eval           # http://localhost:8009/health, /ready, /v1/eval/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/eval/Dockerfile -t compliancewatch-eval .
```

Package `eval_service`, dev port 8009, Postgres schema `eval`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

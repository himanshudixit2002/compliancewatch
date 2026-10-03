# eval service

Part of the ComplianceWatch monorepo. Runs a suite of the eval harness (`evals/harness`) on
request and stores each run with its gates and their drift against the previous run of the same
suite and profile. Design reference: Project Foundation guide, sections 7, 8, 14 and 19.

- **Owns:** Metric runs and drift reports (retrieval recall and precision, grounded rate, citation correctness, extraction acceptance, applicability precision and recall). Golden data lives in `/evals/golden`, the runner in `/evals/harness`. Python package: `eval_service` (`eval` is a builtin)
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** an operator's request to run a suite; the harness and its golden sets. CI and the
  nightly workflow still run the harness directly (`make eval`); review edits are not read yet
- **Emits / publishes:** `eval.run.completed` (outbox, no tenant)

## API

| Route | Who (with a token) | What |
| --- | --- | --- |
| `POST /v1/eval/runs` | admin | Run one suite (`extraction`, `relations`, `qa`) under a profile (`ci`, the default, or `nightly`); 201 with the run, 502 `eval-harness-failed` when the harness stops before measuring |
| `GET /v1/eval/runs` | analyst, reviewer, admin | Runs without their gates, latest first; `suite`, `profile`, `limit` (1 to 100, default 20) |
| `GET /v1/eval/runs/{run_id}` | analyst, reviewer, admin | One run with every gate: name, metric, threshold, value, passed, previous value and drift |

A gate is named `suite.metric[provider]` (`>=baseline` added for a gate held to another suite's
value), which is how drift finds the same gate in the previous run. A run passes when every gate
passes; failing gates are stored like passing ones. The harness runs in a child process
(`python -m cw_evals`), because it builds the services it scores in process and those configure
logging for the whole process; its `latest.json` report is read back from a scratch directory.
Starting a run is synchronous: seconds under `ci`, longer against a real model, bounded by
`CW_EVAL_HARNESS_TIMEOUT_SECONDS`.

Eval runs are platform data: the `eval` schema is in the global group of
`infra/scripts/migration_lint.toml`, and the tables have no tenant_id and no row-level security.

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
make run SERVICE=eval             # http://localhost:8009/health, /ready, /v1/eval/runs
make test                         # unit + contract tests with the coverage gate
docker build -f services/eval/Dockerfile -t compliancewatch-eval .
```

Package `eval_service`, dev port 8009, Postgres schema `eval`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

# pipeline service

Part of the ComplianceWatch monorepo. **Health routes, migrations wiring and one sample Temporal workflow; no source adapters yet.**
Design reference: Project Foundation guide, sections 5, 7, 8, 11 and 14.

- **Owns:** The regulatory intelligence pipeline as Temporal workers: source-crawler (source registry, fetch schedule, raw document store), change-detector (document classification, links to prior documents), doc-parser (clause-level structured text, OCR fallback), rule-extractor (schema-validated RuleCandidates with verified citations), review-service (ReviewTasks, decisions, edit diffs, two-person rule)
- **Owning team:** Regulatory Intelligence; `prompts/` is owned by AI Platform and reviewed by a Regulatory Analyst (guide section 14)
- **Consumes:** Cron per source; admin API; document.discovered; document.classified; document.parsed; rule.candidate.created; workbench UI; LLM gateway API
- **Emits / publishes:** document.discovered, document.classified, document.parsed, rule.candidate.created, rule.published, rule.rejected

## Layout

```
src/pipeline/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work; activities.py: the ingest activities
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters; fakes.py: in-memory adapter and parser
  workflows/       # Temporal workflows; ingest_document.py: discover, fetch, parse
  worker.py        # python -m pipeline.worker: the Temporal worker on task queue "pipeline"
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
alembic.ini, pyproject.toml, Dockerfile
```
## The sample workflow

`pipeline.ingest_document` (`IngestDocumentWorkflow`) runs three activities on
`py_common.temporal.ActivityBase`: `pipeline.discover_document` lists the source through the
kernel's `SourceAdapter` protocol, `pipeline.fetch_document` fetches the bytes and their digest,
`pipeline.parse_document` splits them into clauses through `DocumentParser`. Each activity
declares its own timeouts and retry policy; the workflow does no I/O. Until the source adapters
land, the worker wires the in-memory fakes in `infrastructure/fakes.py` (one sample notification).

```bash
make dev                        # Temporal at localhost:7233
make worker SERVICE=pipeline    # polls task queue "pipeline"
```

Start a run from a script with `py_common.temporal.connect` and
`client.execute_workflow(IngestDocumentWorkflow.run, IngestRequest(source_id=UUID(int=1), since=...), id="ingest-1", task_queue="pipeline")`;
it returns the document id, digest and clause references. The Temporal UI at
http://localhost:8233 shows the run; with `CW_OTEL_ENDPOINT` set the activity spans are in Tempo.
Unit tests run the activities through `temporalio.testing.ActivityEnvironment`; the integration
test runs the workflow on a local Temporal dev server (`make py-test-integration`).
`docs/runbooks/temporal-worker.md` covers a stuck queue or a failed run.

Doc-literal subdirectories at the service root (guide section 13; the CI eval trigger in section 17 watches `services/pipeline/prompts`):

```
adapters/    # SourceAdapter implementations, one file per regulator source (cbic_notifications, cbic_circulars, fssai_orders)
parsers/     # DocumentParser implementations (PDF, HTML, OCR)
prompts/     # Versioned prompt files, each with a version, an owner and at least one eval case
workflows/   # Temporal workflows and activities for the five stages
```

`adapters/`, `parsers/` and `workflows/` may move under `src/pipeline/` when the pipeline slice lands, so that they are importable in the src layout.

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=pipeline
make run SERVICE=pipeline           # http://localhost:8010/health, /ready, /v1/pipeline/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/pipeline/Dockerfile -t compliancewatch-pipeline .
```

Package `pipeline`, dev port 8010, Postgres schema `pipeline`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

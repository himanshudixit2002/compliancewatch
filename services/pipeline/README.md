# pipeline service

Part of the ComplianceWatch monorepo. **Health routes, migrations wiring, one sample Temporal workflow, and the first source adapters: CBIC notifications and circulars, GST Council press releases, GSTN advisories, Maharashtra GST notifications, with PDF and HTML parsers, a change detector and a backfill command.**
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
  application/detector.py  # document type, change kind, referenced notifications
  infrastructure/  # SQLAlchemy models, repositories, Kafka; fakes.py: in-memory adapter and parser
    http.py        # PoliteClient: user agent, robots.txt, per-host delay, retries
    raw_store.py   # content-addressed raw file store (local disk; memory for tests)
    adapters/      # one SourceAdapter per regulator site; registry.py: keys, ids, doc types
    parsers/       # PdfParser (pypdf text layer), HtmlParser, language detection, clause split
  workflows/       # Temporal workflows; ingest_document.py: discover, fetch, parse
  backfill.py      # pipeline-backfill: list, fetch, store, parse and detect from the command line
  testing.py       # FixtureTransport: replays tests/fixtures without the network
  worker.py        # python -m pipeline.worker: the Temporal worker on task queue "pipeline"
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with fakes; adapter conformance over recorded fixtures
  fixtures/        # responses recorded from the regulator sites (README lists what and when)
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

## Sources

| Key | Site | Lists | Fetches | Document type |
| --- | --- | --- | --- | --- |
| `cbic_notifications` | taxinformation.cbic.gov.in | Central Tax notifications per year, newest first, through the portal's JSON API (anonymous token from `POST /api/authenticate-token`, sent as `Authorization1: homeToken ...`) | the English PDF, unwrapped from the `{"data": base64}` envelope; the Hindi PDF path is kept as an alternate | notification |
| `cbic_circulars` | taxinformation.cbic.gov.in | CGST circulars, same API | PDF | circular |
| `gstcouncil_press` | gstcouncil.gov.in | the press-release archive table, page by page until `since` | the PDF, or the Press Information Bureau page a row links to | press_release (announced, not in force) |
| `gstn_advisories` | gst.gov.in | the JSON feed behind News and Updates | the advisory's HTML from the feed item | press_release (advisory) |
| `mahagst_notifications` | mahagst.gov.in | the notifications page (undated rows, user manuals mixed in) | PDF | notification |

Every adapter goes through `PoliteClient`: the crawler user agent, `robots.txt` once per host,
one request per second per host, five tries with exponential backoff on 5xx and transport
errors. Source ids are UUID v5 of the key, so they are the same in every environment.

Parsing keeps the text layer only: a scanned PDF raises `UnparsedDocumentError` and the backfill
reports it as unparsed for a person (OCR is a later parser). Clause references are
`<language>.p<n>`; CBIC gazette PDFs are bilingual and get `hi.` and `en.` clauses in one
document. The detector (`application/detector.py`) reads the title and the first clauses and
returns the document type, the change kind (corrigendum, withdrawal, amendment, extension or
none), the canonical names of the notifications and circulars it cites (via
`domain_kernel.knowledge.normalise_name`), and whether the document is a press release
announcing something not yet in force.

```bash
make backfill SERVICE=pipeline ARGS="--source cbic_notifications --since 2026-01-01 --limit 5"
make backfill SERVICE=pipeline ARGS="--source gstcouncil_press --list-only"
```

Raw files land in `var/raw/<source>/<sha256>.<ext>` and are never overwritten. The adapter
tests replay `tests/fixtures/` through `pipeline.testing.FixtureTransport`; nothing in the
test suite reaches the network. What is not done: OCR, the Kafka `document.discovered` and
`document.parsed` events from the backfill (the workflow's activities are the seam), a source
table in Postgres (the registry is code), and adapters for the other states.

Doc-literal subdirectories at the service root (guide section 13; the CI eval trigger in section 17 watches `services/pipeline/prompts`):

```
adapters/    # pointer: the adapters live in src/pipeline/infrastructure/adapters/
parsers/     # pointer: the parsers live in src/pipeline/infrastructure/parsers/
prompts/     # Versioned prompt files, each with a version, an owner and at least one eval case
workflows/   # pointer: the workflows live in src/pipeline/workflows/
```

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

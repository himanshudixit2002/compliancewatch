# pipeline service

Part of the ComplianceWatch monorepo. **Health routes; the pipeline store (sources, fetched documents, crawl runs, the outbox) and the raw store on disk or S3; the crawl, which reads every source at its cadence from its watermark (a 60-second tick in the worker, behind `CW_PIPELINE_CRAWL_ENABLED`) and ingests what is new in child workflows; the source manager API (the sources with how each stands, an admin's additions, edits and fetches, the documents and their stored files); the ingest workflow, whose `FetchAndStore` keeps each fetched file once and announces it with `document.discovered`; source adapters by type with parameters (CBIC notifications and circulars, GST Council press releases, GSTN advisories, Maharashtra GST notifications), PDF and HTML parsers, a change detector, a backfill command, the crawl report (the F1 check), the rule extractor with its validators behind the llm-gateway, and the labelling tool for the extraction golden set.**
Design reference: Project Foundation guide, sections 5, 7, 8, 11 and 14.

- **Owns:** The regulatory intelligence pipeline as Temporal workers: source-crawler (source registry, fetch schedule, raw document store), change-detector (document classification, links to prior documents), doc-parser (clause-level structured text, OCR fallback), rule-extractor (schema-validated RuleCandidates with verified citations), review-service (ReviewTasks, decisions, edit diffs, two-person rule)
- **Owning team:** Regulatory Intelligence; `prompts/` is owned by AI Platform and reviewed by a Regulatory Analyst (guide section 14)
- **Consumes:** Cron per source; admin API; document.discovered; document.classified; document.parsed; rule.candidate.created; workbench UI; LLM gateway API
- **Emits / publishes:** document.discovered, document.classified, document.parsed, rule.candidate.created, rule.published, rule.rejected

## Layout

```
src/pipeline/
  api/             # routers, request/response schemas, auth dependencies
  api/sources.py, schemas.py, deps.py  # the source manager's routes, bodies and guards
  application/     # use cases, event handlers, unit of work; activities.py: the ingest activities
  application/store_document.py  # StoreDocument: fetch, keep the bytes, record once (FetchAndStore)
  application/sources.py  # the source manager: sync, list, add, edit, documents, stored bytes
  application/crawl.py    # StartCrawl, ScheduleCrawls (the tick), ListNewDocuments, FinishCrawl
  application/report.py   # CrawlReport: runs, failures, gaps, detection delays (the F1 check)
  domain/          # entities, value objects, domain events, repository protocols
  domain/sources.py, raw_documents.py, crawl.py  # Source, RawDocumentRecord, CrawlRun: the rows
  domain/crawl.py          # also where a listing starts and how the watermark moves
  domain/schedule.py       # when a source is due, the crawl's ids, a source's status and freshness
  domain/events.py         # DocumentDiscovered (document.discovered), keyed by its source
  domain/repository.py     # the unit of work and the repositories the store implements
  application/detector.py  # document type, change kind, referenced notifications
  application/extractor.py # LlmRuleExtractor: one gateway call per document, then the validators
  application/validators.py # citations exist and quote the clause, numbers and dates are in the cited text, predicates fit the ontology
  domain/candidate.py      # CANDIDATE_SCHEMA (what the model returns, what a label looks like) and its parser
  domain/numbers.py        # every spelling of an amount or a date a regulator uses (two crore, 21st April, 2026)
  infrastructure/  # SQLAlchemy models, repositories, Kafka; fakes.py: in-memory adapter, parser, catalog
    models.py, repository.py, memory.py  # the store's rows, its Postgres unit of work, its memory one
    http.py        # PoliteClient: user agent, robots.txt, per-host delay (across threads), retries
    raw_store.py   # content-addressed raw file store: S3, local disk, memory
    s3.py          # S3Client: HEAD, PUT and GET signed with Signature Version 4 over httpx2
    adapters/      # one SourceAdapter per regulator site; registry.py: adapter types, sources, catalog
    adapters/catalog.py  # StoreCatalog: the store's sources, adapters built from their rows
    temporal.py    # TemporalCrawls: starts pipeline.crawl_source, one workflow per id
    source_metrics.py  # the freshness gauges SourceStale reads
    parsers/       # PdfParser (pypdf text layer), HtmlParser, SourceParsers, language, clause split
  workflows/       # Temporal workflows; ingest_document.py: discover, fetch, parse, register
  workflows/crawl_source.py  # list from the watermark, ingest the new documents, record the run
  application/knowledge_activities.py  # RegisterDocument: hand the parsed document to the rulebook
  domain/knowledge.py, domain/ports.py # DocumentRecord and the KnowledgeSink port
  infrastructure/rulebook_client.py    # HttpRulebook: the rulebook's write API as a KnowledgeSink
  settings.py      # PipelineSettings: the stores, CW_PIPELINE_KNOWLEDGE_ENABLED, CW_RULEBOOK_URL, ...
  stores.py        # the store and the raw store the settings pick
  backfill.py      # pipeline-backfill: list, fetch, store, parse and detect from the command line
  crawl_report.py  # pipeline-crawl-report: the crawl per source over a window, and the F1 check
  wiring.py        # what the API gets from main: use cases and protocols
  embed.py         # pipeline-embed: embed the stored clauses that have no vector yet
  application/embedding.py  # EmbeddingStage: unembedded clauses to the gateway, vectors to the rulebook
  domain/embedding.py       # embedding_text: the clause with its context header
  label.py         # pipeline-label: index, prepare and check golden extraction cases (make label)
  infrastructure/gateway.py  # GatewayProvider: the llm-gateway as the kernel's LLMProvider; GatewayEmbedder
  infrastructure/prompts.py  # loads prompts/<name>.v<version>.md; the registry holds its digest
prompts/           # extraction.rule_candidate.v1.md (owner regulatory-intelligence)
  testing.py       # FixtureTransport (replays tests/fixtures), ScriptedProvider, ScriptedEmbedder, MemoryRulebook, StubS3, sample_activities
  worker.py        # python -m pipeline.worker: the Temporal worker on task queue "pipeline"
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA); 0001: source, raw_document, crawl_run, outbox_event; 0002: source names, the URL index
tests/
  unit/            # domain and application with fakes; adapter conformance over recorded fixtures
  fixtures/        # responses recorded from the regulator sites, and workflow histories (README lists what and when)
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
alembic.ini, pyproject.toml, Dockerfile
```
## The ingest workflow

`pipeline.ingest_document` (`IngestDocumentWorkflow`) runs its activities on
`py_common.temporal.ActivityBase`, each with its own timeouts and retry policy; the workflow does
no I/O, and the activities do their blocking work (HTTP, the raw store, the database, the PDF
parser) on a thread while they heartbeat, so the worker's event loop never waits on it:

1. `pipeline.discover_document` lists the source through the kernel's `SourceAdapter` protocol
   and returns the first document since `since`. An ingest a crawl starts is handed its document
   as listed (`IngestRequest.discovered`) and skips this step, behind
   `workflow.patched("pipeline-crawl-v1")` (`GIVEN_PATCH`);
2. `pipeline.fetch_and_store` (`FetchAndStore`, the use case `StoreDocument`) fetches the bytes,
   keeps them in the raw store under their digest, and records the document with its
   `document.discovered` in one transaction ([the store](#the-store)). It returns the storage key
   and the digest, never the bytes, so no file passes through Temporal's history. A document
   whose bytes are stored already is a duplicate: nothing is written, the result says
   `duplicate=true` and names the stored key;
3. `pipeline.parse_document` reads the bytes back from the raw store and splits them into
   clauses through `DocumentParser`.

The worker resolves a request's `source_id` through the sources the store holds (`StoreCatalog`,
[Sources](#sources)): it finds the row whose key gives the id and builds the adapter from the
row's adapter type and parameters (`ADAPTER_TYPES[...].validated()`), all over one polite client,
and parses each document with the parsers of its source's document type (`SourceParsers`: the PDF
parser, then the HTML one). An unknown source, or a row the code cannot read (a type it lacks,
parameters the type refuses), is refused and not retried.

`FetchAndStore` replaced `pipeline.fetch_document`, which carried the bytes in its result, behind
`workflow.patched("pipeline-store-v1")` (`STORE_PATCH`): a workflow started before it replays
`FetchDocument` and finishes on the bytes in its history, so `FetchDocument` stays registered and
`ParseRequest` takes either `fetched` (the bytes) or `stored` (the key).
`tests/fixtures/histories` holds two runs recorded before the change and two recorded with the
store and before `GIVEN_PATCH`, and `tests/unit/test_workflow_replay.py` replays all four on
today's workflow (and shows that a workflow without the store's guard would not replay the
first two). Remove `FetchDocument` and the old branch once no workflow started before the store
is open (Temporal's UI lists the running ones).

```bash
make dev                        # Temporal at localhost:7233
make migrate SERVICE=pipeline   # the store's tables
make worker SERVICE=pipeline    # polls task queue "pipeline"
```

Start a run from a script with `py_common.temporal.connect` and
`client.execute_workflow(IngestDocumentWorkflow.run, IngestRequest(source_id=source_id_for("gstn_advisories").value, since=...), id="ingest-1", task_queue="pipeline")`;
this fetches from the live site, politely. It returns the document id, digest, storage key and
clause references. The Temporal UI at http://localhost:8233 shows the run; with
`CW_OTEL_ENDPOINT` set the activity spans are in Tempo. Unit tests run the activities through
`temporalio.testing.ActivityEnvironment`; the integration tests run the workflow on a local
Temporal dev server (`make py-test-integration`) on the sample notification of
`infrastructure/fakes.py`, the plain-text parser and memory stores
(`pipeline.testing.sample_activities`). `docs/runbooks/temporal-worker.md` covers a stuck queue
or a failed run.

With `IngestRequest(knowledge=True, regulator="CBIC")` and `CW_PIPELINE_KNOWLEDGE_ENABLED=true`
the workflow runs a fourth activity, `pipeline.register_document`: it reads the bytes back from
the raw store, parses them again and stores the document and its clauses in the rulebook through
`PUT /v1/rulebook/documents/{id}` (ADR-018), with the raw store's URI of the file, then checks
that the rulebook answered with the clause ids the kernel derives. The step sits behind
`workflow.patched("kag-register-v1")`, so histories recorded before it replay unchanged. The
flag is off by default (owner regulatory-intelligence; it goes when ADR-017 is accepted); off,
the activity answers `skipped` without a call. With the flag on, the request must name the
regulator. A registration that fails (a refused write, a
rulebook outage longer than the retries) does not fail the ingest: the result says
`registered=False` with the reason in `registration_error`. A different parse of stored bytes,
which a parser change can cause, is refused and never retried; the stored clauses stay, since
mentions and citations point into them. Bump the parser's `PARSER_VERSION` with any change that
can alter clause text, so the refusal names both versions; what to do with stored documents
after such a change is an open decision (ADR-018). Deploy the rulebook before the pipeline.

## The crawl

`CW_PIPELINE_CRAWL_ENABLED` (flag `pipeline.crawl`, owner regulatory-intelligence, default off)
turns the crawl on. **A crawl reads the live regulator sites**: leave it off on a laptop, in
`make product` (which passes `CW_PIPELINE_CRAWL_ENABLED=false` whatever `.env` says) and in CI.
The tests and the journey crawl recorded responses only. The `source` table is the only
schedule; no Temporal schedule holds a copy.

- **The tick.** With the flag on, the worker runs `pipeline-crawl-tick` every 60 seconds
  (`ScheduleCrawls`). A source is due when it is enabled and not paused, no crawl of it runs, and
  its cadence has passed since its last crawl started (`domain/schedule.py`). For each one the
  tick locks the source's row, records a crawl run whose id is derived from the workflow id
  `pipeline-crawl-<key>-<cadence slot start>`, and only then, with the transaction closed, starts
  the workflow with the id reuse policy `REJECT_DUPLICATE`. A second tick in the same slot finds
  the run recorded (and Temporal would refuse the id), so a double tick starts nothing twice.
- **By hand.** `POST /v1/pipeline/sources/{key}/fetch` does the same for one source at once,
  under `pipeline-crawl-<key>-manual-<request>`, and answers 202 with the run's id; 409 while a
  crawl of the source runs, 503 while the flag is off. A paused source may be fetched by hand.
- **The workflow** `pipeline.crawl_source` (`CrawlSourceWorkflow`, two hours at most):
  1. `pipeline.list_new_documents` lists the source since a week before its watermark (the last
     30 days for a source without one), with no transaction open, and leaves out the URLs a
     stored document of the source was listed at (`known_urls`, on migration 0002's index); at
     most 50 of the rest come back, newest first;
  2. each new document is ingested by a child `pipeline.ingest_document` that takes it as listed,
     at most three at a time, under the id `pipeline-ingest-<key>-<URL digest>` that may be
     reused only after a failure, so a document two crawls list is ingested once. Children are
     abandoned, not cancelled, when the crawl ends early: what they store stays stored;
  3. `pipeline.finish_crawl` records the run's counts (`listed`; `stored`, `duplicates` and
     `failed` of the new documents) and end, and the source's last listing (`last_fetch_at`),
     watermark and `last_error`, in one transaction. A child that failed after its bytes were
     stored (a parse failure) counts as stored.
- **The watermark** moves to the newest publication date stored, never past a listed document
  that is not stored (failed, beyond the cap of 50, or busy in another crawl), so the next crawl
  lists that one again. Undated documents are listed by every crawl and never hold it back. A
  document whose bytes change behind a URL already stored is not fetched again by the crawl.
- **Failures are recorded, not raised.** A listing that fails ends the run as failed with the
  error on the run and on the source (`status: failing`), and leaves `last_fetch_at` and the
  watermark as they were; the next tick tries again after a cadence. Documents that fail leave
  the run completed and name themselves in the source's `last_error`. A run whose workflow was
  lost (a timeout, a worker gone, a start that never happened) is closed as abandoned by the next
  start three hours after it began. A start Temporal refuses closes its run with why.

The app reports each source's freshness while crawling is on (`infrastructure/source_metrics.py`):
`pipeline_source_freshness_seconds{source}`, the time since a crawl last listed it (since it was
added, before), and `pipeline_source_cadence_seconds{source}`. The `SourceStale` alert pages when a
source has not been listed for more than two cadences
([docs/runbooks/source-stale.md](../../docs/runbooks/source-stale.md)).

`pipeline-crawl-report --days 30` (`make crawl-report ARGS="--days 30"` on the dev stack) is the
F1 check: per source the runs and failures in the window, the longest gap between successful
listings from the window's start to now, and where documents carry a date the detection delay from
the start of that day in India to the first fetch (an upper bound: regulators date documents, not
hours). F1 is met for `--f1-source` (`cbic_notifications`) when no gap passed `--target-hours`
(6) and the last crawl recorded no error; the command exits 0 then, 1 otherwise.

## The source manager

The routes are the regulatory team's (composition class admin, so the public listener serves them
in `token` mode only). The reads need a regulatory role (analyst, reviewer or admin) a token names;
the writes an admin, or in `header` and `dual` mode without a bearer the shared write token
(`CW_RULEBOOK_WRITE_TOKEN` in `x-cw-write-token`; unset, writes answer 503
`pipeline-writes-disabled`). Every write names its actor (`actor_id`, which a user's token
overrides) and a reason of at least ten characters, and writes its `audit.event` row, of no
tenant, in the transaction of the change.

| Route | What |
| --- | --- |
| `GET /v1/pipeline/sources` | every source with its name, adapter type and parameters, regulator, site, document type, cadence, switches, `status` (`fetching` while a crawl runs, else `paused`, `failing` or `healthy`), document count, last listing, `freshness` (`fresh`, `late`, `stale` or `never`, the age in seconds and in cadences), last error, watermark and latest run |
| `POST /v1/pipeline/sources` | add a source of a registry adapter type with that type's parameters, which it checks (422); 409 for a key taken; audited as `pipeline.source.add` |
| `PATCH /v1/pipeline/sources/{key}` | change its name, cadence, enabled or paused switch, or parameters; audited as `pipeline.source.edit` with the source before and after, unless nothing changed |
| `POST /v1/pipeline/sources/{key}/fetch` | start a crawl now: 202 with the run and workflow ids; audited as `pipeline.source.fetch` |
| `GET /v1/pipeline/sources/{key}/documents` | the source's documents a page at a time (`limit`, `cursor`), newest publication first, undated last |
| `GET /v1/pipeline/documents/{document_id}` | one stored document's record |
| `GET /v1/pipeline/documents/{document_id}/raw` | its bytes from the raw store with the content type it was fetched with, served only when their SHA-256 is the record's (502 otherwise), with the digest as the ETag, inline, sandboxed and never sniffed |

The spec is `packages/contracts/openapi/pipeline.v1.json` (`make openapi SERVICE=pipeline`).

## The store

Migration 0001 creates the `pipeline` schema's tables and 0002 adds the sources' names and the
index the crawl looks known URLs up by (`source_key`, `source_url`). They hold regulatory data,
the same for every tenant: no `tenant_id` and no row-level security, and
`infra/scripts/migration_lint.toml` exempts the three with the reason.

| Table | One row per | Columns |
| --- | --- | --- |
| `source` | source the pipeline reads | `key`, `name`, `adapter_type`, `parameters` (JSON), `cadence`, `enabled`, `paused`, `last_fetch_at`, `watermark` (JSON, `{"published_on": "2026-10-01"}`), `last_error`, `created_at`, `updated_at` |
| `raw_document` | fetched file, by content | `id` (the first half of the SHA-256, checked by a constraint), `source_key`, `source_url`, `external_ref`, `fetched_at`, `published_on`, `content_type`, `size`, `sha256` (unique), `storage_key`, `title`, `status` (`discovered`, `parsed`, `failed`, `irrelevant`) |
| `crawl_run` | crawl of one source | `id`, `source_key`, `started_at`, `finished_at`, `status` (`running`, `completed`, `failed`), the counts `listed`, `stored`, `duplicates`, `failed`, and `error` |
| `outbox_event` | event to publish | py-common's outbox (ADR-005) |

A raw document never changes but for its status and is never deleted: a trigger refuses the
rest. The worker adds the built-in sources the table lacks when it starts (`SyncSources`, which
also names a built-in row stored before names and changes nothing else), and so does the app on
its store; `FetchAndStore` adds a source's row the first time it stores one of its documents.
None of them changes a row that exists: an admin's edits stay. Crawl runs, `last_fetch_at`, the
watermark and `last_error` are written by the crawl ([The crawl](#the-crawl)).

The unit of work (`domain/repository.py`) has a repository per table, the outbox as its event
sink and `audit.event` as its audit sink (py-common's `AuditWriter`): `infrastructure/repository.py`
on Postgres, one transaction with no tenant setting
(`PostgresUnitOfWorkFactory`, and `on_connection` for a consumer's transaction), and
`infrastructure/memory.py` in memory for tests. `CW_PIPELINE_STORE` picks one (`postgres` by
default, `memory`); the worker refuses `memory`, since its activities record what they fetch.

`document.discovered` 1.0.0 carries the source and document ids, the regulator, the URL, the
listing's reference, title and date, the digest, the media type, the fetch time and the raw
store's URI of the file. It has no tenant, and the outbox keys it by the source. The outbox relay
publishes it: `make relay SERVICE=pipeline`, or `cw-mvp worker`, which runs a relay for every
schema with an outbox table while `CW_WORKER_KAFKA_ENABLED` is on. Nothing consumes the topic
yet.

## The raw store

A fetched file is kept under a key that names the SHA-256 of its bytes,
`<first two hex digits>/<sha256>`, so the same bytes always land under the same key: a refetch
never stores a second copy, and a file is never overwritten. Reading a key checks the bytes
against the digest it names. `CW_PIPELINE_RAW_STORE` picks the store:

| Store | Where | Settings |
| --- | --- | --- |
| `local` (default) | `<dir>/<ab>/<sha256>`, written through a temporary file and a rename | `CW_PIPELINE_RAW_DIR` (`var/raw`) |
| `memory` | a dict in the process | none; for tests |
| `s3` | `s3://<bucket>/<prefix><ab>/<sha256>` | `CW_PIPELINE_RAW_BUCKET`, `CW_PIPELINE_RAW_PREFIX` (`raw/`), `CW_PIPELINE_RAW_REGION` (`ap-south-1`), `CW_PIPELINE_RAW_ENDPOINT_URL`, `CW_PIPELINE_RAW_ACCESS_KEY_ID`, `CW_PIPELINE_RAW_SECRET_ACCESS_KEY`, `CW_PIPELINE_RAW_SESSION_TOKEN`, `CW_PIPELINE_RAW_ENCRYPTION`, `CW_PIPELINE_RAW_KMS_KEY_ID` |

The S3 store writes with server-side encryption: `CW_PIPELINE_RAW_ENCRYPTION=AES256` (SSE-S3, the
default) or `aws:kms` with `CW_PIPELINE_RAW_KMS_KEY_ID` (the bucket's AWS-managed key when it is
empty); `none` is for a local MinIO without a key service and is refused in staging and
production. A write first asks whether the key exists and then puts with `If-None-Match: *`, so
a versioned bucket gets no second version from a refetch or from two writers at once. Bucket
policy (versioning, object lock, lifecycle) is the infrastructure's. The client is
`infrastructure/s3.py`: path-style URLs on `CW_PIPELINE_RAW_ENDPOINT_URL` (MinIO in dev, any
S3-compatible store) and virtual-hosted ones on AWS, a static access key (with its session token
when it is temporary), Signature Version 4 checked against AWS's published examples, and three
tries of a call that a 5xx or a transport error failed. No AWS SDK is a dependency, so a role
from the instance or IRSA is not picked up: give the key. On MinIO:

```bash
CW_PIPELINE_RAW_STORE=s3 CW_PIPELINE_RAW_BUCKET=cw-raw-dev \
CW_PIPELINE_RAW_ENDPOINT_URL=http://localhost:9000 CW_PIPELINE_RAW_REGION=us-east-1 \
CW_PIPELINE_RAW_ACCESS_KEY_ID=<user> CW_PIPELINE_RAW_SECRET_ACCESS_KEY=<password> \
CW_PIPELINE_RAW_ENCRYPTION=none make worker SERVICE=pipeline
```

`cw-mvp check-config` refuses a raw store other than `s3` in staging and production while the
worker fetches documents (`CW_WORKER_TEMPORAL_ENABLED`): a local or memory store loses the files
with the machine or the process.

## Knowledge extraction (ADR-017)

Once a document is registered, the ingest runs the child workflow `pipeline.extract_knowledge`
(behind `workflow.patched("kag-extract-v1")`, same flag). It has three activities:

1. `pipeline.extract_mentions` runs the mention grammar (`domain/grammar.py`, `grammar@1`) over
   the stored clauses. The grammar reads notification and circular numbers (and notification
   numbers in Hindi), sections and sub-sections, rules and sub-rules with their statute
   (`39(6)@cgst-act`, `61(1)(i)@cgst-rules`), GST forms, HSN and SAC codes after their keyword,
   tax rates near a tax word, rupee amounts near a threshold word, and state names. It matches
   the text as parsed, so a mention's span points at exactly its characters. The mentions go to
   the rulebook, which aligns them or queues them for review.
2. `pipeline.propose_relations` asks the model, through the gateway with the registered prompt
   `extraction.rule_relations@1` (`prompts/extraction.rule_relations.v1.md`), which of the
   grammar's targets the document acts on and how. The JSON schema is built per call, so targets,
   evidence clauses and rule keys are closed lists. The answer goes through
   `domain/relations.parse_relations` and the validator chain in
   `application/relation_validators.py`: quote and date against the clause, target type, and
   agreement with the change detector. Nothing is written here.
3. `pipeline.submit_relations` stages the result as relation candidates for review. It is a
   separate activity, so a failed write is retried without asking the model again.

`application/stages.py` is the stage template (validate, process, check); `MentionStage` and
`RelationStage` are its two stages, called from the activities. A failed extraction is reported
in the ingest result (`knowledge_error`) and does not fail the ingest. The relation suite of the
eval harness (`make eval`) runs the same stages over `evals/golden/relations`.

## Clause embeddings

Between registration and the extraction child, the ingest runs `pipeline.embed_clauses`
(behind `workflow.patched("kag-embed-v1")`, same flag) so the rulebook's clause search has a
vector for every clause. `EmbeddingStage` (`application/embedding.py`) pages through the
document's clauses that have no vector from the run's model
(`GET /v1/rulebook/clauses/unembedded`), 64 at a time, embeds each page in one gateway call
(`POST /v1/llm-gateway/embeddings`, feature `retrieval`) and stores the vectors
(`PUT /v1/rulebook/clauses/embeddings`; a clause keeps its first vector from a model). Each
text is the clause behind a header (`domain/embedding.embedding_text`): regulator, document
type, number or title, date and clause reference, cut at 6,000 characters.

Vectors from two models do not compare, so a run pins one: it first sends a one-line probe to
learn which model the gateway's retrieval route serves, asks the rulebook about that model's
gaps, and refuses any batch from another model. An answer of another length than 512, another
count or another model raises `EmbeddingContractError`, which is not retried. A failed embedding
is reported in the ingest result (`embedding_error`; `clauses_embedded` counts the vectors
stored) and does not fail the ingest.

`pipeline-embed` runs the same stage over every document: it catches up clauses registered
before this step, and with `--model` fills a new model's vectors before the gateway's route
(`CW_LLM_ROUTES__RETRIEVAL`) switches to it. It uses the worker's `CW_RULEBOOK_URL`,
`CW_RULEBOOK_WRITE_TOKEN`, `CW_LLM_GATEWAY_URL` and service client.

## Service token

Once `CW_SERVICE_CLIENT_SECRET` is set, every call the worker and `pipeline-embed` make to the
rulebook and the gateway carries the pipeline's own access token (`Authorization: Bearer`),
which the identity service issues for client `CW_SERVICE_CLIENT_ID` (`make worker` defaults it
to `pipeline`). The client needs the rulebook:write scope for the writes and llm:call for the
model calls; locally identity creates it from `identity_dev_clients.toml`. The token is cached
until a minute before it expires, and a 401 fetches a new one and resends the request once.
When identity cannot issue a token, a rulebook call fails as an outage and a gateway call as a
gateway error, and the activity retries.

The rulebook's writes still carry `CW_RULEBOOK_WRITE_TOKEN` while it is set, so the same worker
runs against a rulebook in `header` mode (which reads the write token), `dual` mode (the bearer
when one is sent) and `token` mode (the bearer alone). Unset the write token once the rulebook
runs in `token` mode. Without the client secret the worker sends no bearer and behaves as before.

```bash
uv run --package compliancewatch-pipeline pipeline-embed --limit 500
uv run --package compliancewatch-pipeline pipeline-embed --model voyage/voyage-3.5-lite
```

## Sources

An adapter type reads one regulator site (`infrastructure/adapters/registry.py`,
`ADAPTER_TYPES`): its regulator, its site, the parameters it takes, which a pydantic model checks
(anything it does not name is refused), and how it builds the adapter. A source is a key, an
adapter type with its parameters, a cadence and a name; its regulator and document type follow
from the type and the parameters. The built-in sources (`SOURCES`) are the registry's; the worker
adds their rows to the store when it starts, and an admin adds others through the source manager.
The worker reads every source from the store (`StoreCatalog`), so a new source or an edit takes
effect at the next activity.

| Key (name) | Adapter type and parameters | Cadence | Lists | Fetches | Document type |
| --- | --- | --- | --- | --- | --- |
| `cbic_notifications` (CBIC Central Tax notifications) | `cbic`: `listing` notifications, `category` Central Tax | 2 h | notifications per year, newest first, through the portal's JSON API (anonymous token from `POST /api/authenticate-token`, sent as `Authorization1: homeToken ...`) | the English PDF, unwrapped from the `{"data": base64}` envelope; the Hindi PDF path is kept as an alternate | notification |
| `cbic_circulars` (CBIC CGST circulars) | `cbic`: `listing` circulars, `category` Circulars CGST | 6 h | circulars, same API | PDF | circular |
| `gstcouncil_press` (GST Council press releases) | `gstcouncil` | 6 h | the press-release archive table, page by page until `since` | the PDF, or the Press Information Bureau page a row links to | press_release (announced, not in force) |
| `gstn_advisories` (GSTN advisories) | `gstn` | 3 h | the JSON feed behind News and Updates | the advisory's HTML from the feed item | press_release (advisory) |
| `mahagst_notifications` (Maharashtra GST notifications) | `mahagst` | 12 h | the notifications page (undated rows, user manuals mixed in) | PDF | notification |

The CBIC type is one adapter for both portal listings: `listing` picks the API path and the
fields of its items, `category` the portal's category. A category is accepted only when its
listing is recorded under `tests/fixtures/cbic` (`cbic.RECORDED_CATEGORIES`), so another
category comes with its fixture. The cadences are what the crawl reads each source at, until an
admin changes them.

Every adapter goes through `PoliteClient`: the crawler user agent, `robots.txt` once per host,
one request per second per host (across the threads the activities fetch on), five tries with
exponential backoff on 5xx and transport errors. Source ids are UUID v5 of the key, so they are
the same in every environment.

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

The backfill keeps raw files in a local raw store (`--store`, `var/raw`), under the same
content keys, never overwritten. The adapter tests replay `tests/fixtures/` through
`pipeline.testing.FixtureTransport`; nothing in the test suite reaches the network. The crawl's
tests use the test adapter type `recorded` (`pipeline.testing.RECORDED_TYPE`), which lists
recorded CBIC notifications from the recorded listings and fetches their recorded PDFs. What is
not done: OCR; a parser chain and a queue for documents that do not parse (a crawl counts such a
document as stored and its ingest fails); uploads; `document.parsed` (the ingest's
`FetchAndStore` writes `document.discovered`, the backfill writes no event); and adapters for the
other states.

## Extraction

`LlmRuleExtractor` renders the parsed document as `[ref] text` lines, sends the registered
prompt `extraction.rule_candidate@1` with `CANDIDATE_SCHEMA` through the llm-gateway (never a
provider directly; the gateway checks the prompt reference against its registry, where the
file's digest is recorded), reads the answer as `CandidateFields` and runs the validators.
Every model-dependent path is exercised in tests with `pipeline.testing.ScriptedProvider`; the
eval harness runs the same code against the gateway's fake provider and, nightly, a real one.

The validators are deterministic and never discard a candidate; they attach issues that send it
to review: `citation_missing_clause`, `citation_quote_not_found`, `amount_not_in_clause`,
`due_day_not_in_clause`, `due_in_days_not_in_clause`, `date_not_in_cited_clauses`,
`dates_out_of_order`, `predicate_invalid`, `reference_empty`, plus `output_unparseable` when
the answer is not a candidate. The numeric check accepts the spellings regulators use: `2 crore`,
`two crore`, `2,00,00,000`, `twenty-first day of April, 2026`, `21.04.2026`.

```bash
make label ARGS="check"                                   # every golden case is well formed
make label ARGS="prepare --index evals/golden/extraction/cbic_notifications/index.yaml --limit 5"
make eval                                                 # scripted + fake gateway, section 8 gates
```

The golden set and its workflow are described in `evals/golden/extraction/README.md`; the
harness in `evals/harness/README.md`.

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
make migrate SERVICE=pipeline     # source, raw_document, crawl_run, outbox_event
make run SERVICE=pipeline           # http://localhost:8010/health, /ready, /v1/pipeline/sources
make worker SERVICE=pipeline      # the Temporal worker of the crawl and the ingest; with
                                  # CW_PIPELINE_CRAWL_ENABLED=true it crawls the live sites
make crawl-report ARGS="--days 30"  # the crawl per source and the F1 check
make relay SERVICE=pipeline       # publishes document.discovered from the outbox
make test                         # unit + contract tests with the coverage gate
docker build -f services/pipeline/Dockerfile -t compliancewatch-pipeline .
```

Package `pipeline`, dev port 8010, Postgres schema `pipeline`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

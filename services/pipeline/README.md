# pipeline service

Part of the ComplianceWatch monorepo. **Health routes; the pipeline store (sources, fetched documents, crawl runs, the tasks people work, the outbox) and the raw store on disk or S3; the crawl, which reads every source at its cadence from its watermark (a 60-second tick in the worker, behind `CW_PIPELINE_CRAWL_ENABLED`) and ingests what is new in child workflows; the source manager API (the sources with how each stands, an admin's additions, edits and fetches, the documents and their stored files); uploads of a document to a source; the ingest workflow, whose `FetchAndStore` keeps each fetched file once and announces it with `document.discovered`, whose parse goes through the parser chain (the PDF's text layer, a table-aware PDF parser, HTML and table-aware HTML) and announces `document.parsed`, and whose classify step records what each document is with `document.classified` and holds a conflict for a person's triage; manual parse, where a document no parser reads opens a task an analyst resolves with a transcript; the rule extraction in the workflow, behind `CW_PIPELINE_EXTRACTION_ENABLED`, which stores one rule candidate per classified document and announces it with `rule.candidate.created`; source adapters by type with parameters (CBIC notifications and circulars, GST Council press releases, GSTN advisories, Maharashtra GST notifications, and upload-only statutes: the CGST Act, the CGST Rules, the IGST Act), a change detector, the backfill from a plan through the crawl workflow with its report, the sweep of the classified backlog into the extraction, the operations API (every source's crawl runs and documents, a person's retry of a stored document, the outbox's dead rows and their requeue), the crawl report (the F1 check), the rule extractor with its validators behind the llm-gateway, and the labelling tool for the extraction golden set.**
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
  api/uploads.py, tasks.py  # an upload to a source (multipart, size-capped); the task queue
  application/     # use cases, event handlers, unit of work; activities.py: the ingest activities
  application/store_document.py  # StoreDocument: fetch, keep the bytes, record once (FetchAndStore)
  application/sources.py  # the source manager: sync, list, add, edit, documents, stored bytes
  application/crawl.py    # StartCrawl, ScheduleCrawls (the tick), ListNewDocuments, FinishCrawl
  application/report.py   # CrawlReport: runs, failures, gaps, detection delays (the F1 check)
  application/uploads.py  # UploadDocument: check, store, record, audit, start the ingest
  application/tasks.py    # ListTasks, ResolveTask (a transcript, a triage's decision), DismissTask
  application/classify.py # ClassifyDocument: the classify step and its triage task
  application/extraction.py  # ExtractRules (the model, no write), StoreExtraction (the candidate
                             # and its event), RuleExtractionStage (once more when not a candidate)
  application/operations.py  # ListRuns, ListDocuments, RetryDocument, ListDeadEvents, RequeueEvent
  application/backlog.py  # ExtractionBacklog: the documents waiting as classified, per source
  application/backfill.py # PlanDryRun, RunBackfill (crawls through the workflow), BackfillReport
  api/operations.py, operations_schemas.py  # the operations routes: runs, documents, retry, dead outbox
  domain/          # entities, value objects, domain events, repository protocols
  domain/sources.py, raw_documents.py, crawl.py  # Source, RawDocumentRecord, CrawlRun: the rows
  domain/crawl.py          # also where a listing starts and how the watermark moves
  domain/schedule.py       # when a source is due, the crawl's ids, a source's status and freshness
  domain/events.py         # DocumentDiscovered, DocumentParsed, DocumentClassified and
                           # RuleCandidateCreated, keyed by their source
  domain/tasks.py          # PipelineTask: a manual parse or a triage, open, resolved, dismissed
  domain/classification.py # Classification, its route and status, a triage's decision
  domain/extraction.py     # RuleExtraction, its candidate id, its event, a suggested rule key
  domain/retry.py          # DocumentRetry: a person's retry of a stored document, its stage, its ingest's id
  domain/outbox.py         # OutboxEvent as the operations routes read it, the dead rows' keyset
  domain/backfill.py       # BackfillRow: a plan's row, its listing window and its limits
  domain/structure.py      # blocks (headings, paragraphs, tables) and the clauses they become
  domain/transcripts.py    # an analyst's transcript: its JSON shape, its checks, manual@1
  domain/language.py       # en, hi or mul from the letters of a text
  domain/repository.py     # the unit of work and the repositories the store implements
  application/detector.py  # document type with its confidence, relevance, change kind, references
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
    temporal.py    # TemporalCrawls and TemporalIngests: start the crawl and an ingest by name
    source_metrics.py  # the freshness gauges SourceStale reads
    parsers/       # ParserChain over PdfParser (text layer), PdfTableParser, HtmlParser,
                   # HtmlTableParser; the clause split
    adapters/upload.py   # UploadOnlyAdapter: lists and fetches nothing (the statutes)
    task_metrics.py  # the open-task gauges ParseFailureQueueHigh and TriageQueueStale read
  workflows/       # Temporal workflows; ingest_document.py: discover, fetch, parse, register
  workflows/crawl_source.py  # list from the watermark, ingest the new documents, record the run
  workflows/extract_rules.py # ask the model, wait out a used-up budget, store the candidate
  workflows/extract_backlog.py # the sweep: each waiting document's extraction as a child
  application/knowledge_activities.py  # RegisterDocument: hand the parsed document to the rulebook
  domain/knowledge.py, domain/ports.py # DocumentRecord and the KnowledgeSink port
  infrastructure/rulebook_client.py    # HttpRulebook: the rulebook's write API as a KnowledgeSink
  settings.py      # PipelineSettings: the stores, CW_PIPELINE_KNOWLEDGE_ENABLED, CW_RULEBOOK_URL, ...
  stores.py        # the store and the raw store the settings pick
  backfill.py      # pipeline-backfill: a plan's dry run, its crawls through the workflow, the report
  extract_backlog.py  # pipeline-extract-backlog: count the classified backlog, start the sweep
  crawl_report.py  # pipeline-crawl-report: the crawl per source over a window, and the F1 check
  wiring.py        # what the API gets from main: use cases and protocols
  embed.py         # pipeline-embed: embed the stored clauses that have no vector yet
  application/embedding.py  # EmbeddingStage: unembedded clauses to the gateway, vectors to the rulebook
  domain/embedding.py       # embedding_text: the clause with its context header
  label.py         # pipeline-label: index, prepare and check golden extraction cases (make label)
  infrastructure/gateway.py  # GatewayProvider: the llm-gateway as the kernel's LLMProvider; GatewayEmbedder
  infrastructure/prompts.py  # loads prompts/<name>.v<version>.md; the registry holds its digest
prompts/           # extraction.rule_candidate.v1.md (owner regulatory-intelligence)
  testing.py       # FixtureTransport (replays tests/fixtures), ScriptedProvider, AnswersInTurn, ScriptedEmbedder, MemoryRulebook, StubS3, sample_activities
  worker.py        # python -m pipeline.worker: the Temporal worker on task queue "pipeline"
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA); 0001: source, raw_document, crawl_run, outbox_event; 0002: source names, the URL index; 0003: pipeline_task, the parse of each document; 0004: document_classification, rule_extraction, the statuses of a classified document; 0005: crawl runs' trigger and workflow id, document_retry, a retry's classification
backfill-plan.yaml # the backfill plan: the notifications the seed rules cite, then about 200 recent ones
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
   clauses through the parser chain ([The parser chain](#the-parser-chain)), the way the
   document's record says: as the type its uploader gave, by the parser that parsed it before,
   from the analyst's transcript once there is one. In one transaction it records the parse on
   the record (`parsed` for a document not parsed before, `parser_version`), writes
   `document.parsed` when that changed anything, and closes a manual-parse task the parse made
   needless;
4. `pipeline.classify_document` classifies a stored document, behind
   `workflow.patched("pipeline-classify-v1")` (`CLASSIFY_PATCH`): [Classification and
   triage](#classification-and-triage). An irrelevant document and a conflict end the ingest
   there, unregistered; the rest is registered as the type it was classified as;
5. with the extraction on, a notification, circular or act amendment that was classified and
   registered gets its rule candidate extracted in a child the ingest starts and leaves running,
   behind `workflow.patched("pipeline-extraction-v1")` (`EXTRACTION_PATCH`):
   [Extraction in the workflow](#extraction-in-the-workflow).

An ingest an upload, a manual parse's resolution or a triage's resolution starts is handed the
document as stored (`IngestRequest.stored`, with `transcript_key` naming the analyst's transcript
for a manual parse) and skips the first two steps, behind `workflow.patched("pipeline-stored-v1")`
(`STORED_PATCH`).

A stored document no parser reads (`UnparsedDocumentError`, or `UnsupportedDocumentError` for a
media type no parser takes) does not fail the ingest, behind
`workflow.patched("pipeline-parse-v1")` (`PARSE_PATCH`): `pipeline.open_manual_parse` sets the
document `failed` and opens its manual-parse task in one transaction, and the ingest ends there
with `parse_failed=true` and the task's id, so nothing of the document is registered
([Manual parse](#manual-parse-and-uploads)). A document with a task open already keeps it, so a
retry or a second ingest of the same bytes opens none. A crawl counts such a document as stored.

The worker resolves a request's `source_id` through the sources the store holds (`StoreCatalog`,
[Sources](#sources)): it finds the row whose key gives the id and builds the adapter from the
row's adapter type and parameters (`ADAPTER_TYPES[...].validated()`), all over one polite client,
and parses each document through the chain as its source's document type unless its record
names another (`ParserChain`). An unknown source, or a row the code cannot read (a type it lacks,
parameters the type refuses), is refused and not retried.

`FetchAndStore` replaced `pipeline.fetch_document`, which carried the bytes in its result, behind
`workflow.patched("pipeline-store-v1")` (`STORE_PATCH`): a workflow started before it replays
`FetchDocument` and finishes on the bytes in its history, so `FetchDocument` stays registered and
`ParseRequest` takes either `fetched` (the bytes) or `stored` (the key).
`tests/fixtures/histories` holds two runs recorded before the change, two recorded with the
store and before `GIVEN_PATCH`, three recorded with the crawl's given document and before
`PARSE_PATCH` (one whose PDF has no text layer, so its parse failed the ingest), and five
recorded with the parser chain and before `CLASSIFY_PATCH` (a crawl's document with knowledge off
and on, an upload, a statute's transcript, a scan whose manual-parse task opened), and
`tests/unit/test_workflow_replay.py` replays all twelve on today's workflow (and shows that a
workflow without the store's guard, the parse's or the classify step's would not replay them). Remove
`FetchDocument` and the old branch once no workflow started before the store is open (Temporal's
UI lists the running ones).

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
`registered=False` with the reason in `registration_error`. The registration parses the bytes
again the way the parse did (the record names the parser) and sends the parser's name and version
with the clauses. The rulebook keeps the first parse of a document (ADR-018, addendum of
2026-10-06): a parse by another parser version is answered with the stored clauses and their
parser, never a 409, and the pipeline then checks that those clauses carry the ids the kernel
derives for their refs. A different parse by the same parser version is refused and never
retried: bump the parser's `PARSER_VERSION` with any change that can alter clause text. Deploy the
rulebook before the pipeline.

Statutes are registered and their clauses embedded like any document, so rules can cite them,
but nothing is extracted from them: the ingest asks `domain.candidate.is_extracted` of the
document type before the extraction child, and the rule extraction step that is to follow it
asks the same.

## The parser chain

`infrastructure/parsers/chain.py` (`ParserChain`) parses every document by its media type: the
first parser of the chain that takes the type and reads the bytes gives its clauses, and names
itself on them (`name@version`).

| Parser | Takes | Gives |
| --- | --- | --- |
| `pdf@1` (`PdfParser`) | PDF | the text layer, split into paragraphs and numbered items; it gives way on a PDF with tables |
| `pdf-tables@1` (`PdfTableParser`) | PDF | the same text, read in pypdf's layout mode, with each table row one clause of its cells joined by ` \| ` |
| `html@1` (`HtmlParser`) | HTML | the text of the page's blocks, every table cell a paragraph; it gives way on a page with a data table |
| `html-tables@1` (`HtmlTableParser`) | HTML | headings, paragraphs, and each table row one clause of its cells, the header row first |
| `manual@1` (`domain.transcripts`) | an analyst's transcript | the transcript's blocks, the same way |

A parser that gives way (`DeclinedDocumentError`) is asked again, to parse as it always did, when
no later one reads the document, so a PDF the text-layer parser read before still parses. The
text-layer parsers give the same clauses as before for every document they parse, so `pdf@1` and
`html@1` keep their versions. The table-aware PDF parser finds rows on the layout grid: a wrapped
row (a line of three or more cells with lines hanging under its last cell, as the entries of a
jurisdiction table), aligned rows (lines whose cells start in the same columns), a single row of a
row's columns found elsewhere in the document, and a cell's second paragraph; the rest is text.
It joins again what the grid splits (a superscript ordinal, `13th`; a lone full stop, `102.`).
pypdf, already a dependency, is all it uses. The recorded 10/2025-Central Tax (a table of
Commissionerates and their districts) is its test: every row comes out as `“23. | Chennai Outer |
Districts of Viluppuram, ...`.

Clause refs are `<language>.p<n>` for every parser, counted per language in document order, so
the rulebook takes them as they are and the same bytes give the same refs and ids every time.
Each document keeps its parser: its record names the parser of its last parse
(`raw_document.parser_version`), and the chain tries that one first, never letting it give way,
so a document parsed before a new parser joined the chain keeps its clauses and their ids while
the code has its parser. A version the chain no longer has is passed over; the rulebook then keeps
the first parse it stored (ADR-018). A document an analyst transcribed is always parsed from the
transcript its record names (`raw_document.transcript_key`).

When no parser reads a document, `UnparsedDocumentError` names each parser's reason (`pdf@1:
UnparsedDocumentError: the PDF has no text layer; pdf-tables@1: ...`); a parser that cannot open
the bytes counts as one that does not read them. OCR is not built.

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
- **A backfill.** `pipeline-backfill --workflow` starts the same workflow for each row of a plan
  with the trigger `backfill` ([Operations](#operations)): behind the patch
  `pipeline-backfill-v1`, the crawl lists the row's own window (from a date below the watermark,
  up to another, only the references the row names) and ingests up to the row's limit (500 at
  most) instead of 50. A backfill lists only part of history, so it is none of the source's
  crawls: its end records its run and leaves the source as it was, its watermark (none
  included), last listing and error, and the schedule's crawls go on from where they were. A
  crawl that names no window records no marker, so every other crawl's history replays as it was.
  Each run says its `trigger` (`schedule`, `manual` or `backfill`) and its workflow id.
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
     watermark and `last_error` (a backfill's, the run alone), in one transaction. A child that
     failed after its bytes were stored (a parse failure) counts as stored.
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
| `GET /v1/pipeline/documents/{document_id}` | one stored document's record, with the type the pipeline reads it as, its classification, its extraction by the current prompt and its retries ([Operations](#operations)) |
| `GET /v1/pipeline/documents/{document_id}/raw` | its bytes from the raw store with the content type it was fetched with, served only when their SHA-256 is the record's (502 otherwise), with the digest as the ETag, inline, sandboxed and never sniffed |
| `POST /v1/pipeline/sources/{key}/uploads` | upload a document to the source ([Manual parse and uploads](#manual-parse-and-uploads)): 202 with the stored document and its ingest's workflow id; audited as `pipeline.document.upload` |
| `GET /v1/pipeline/tasks` | the tasks people work on stored documents, of a `status` (`open`, `resolved`, `dismissed`) and a `kind` (`manual_parse`, `triage`), both optional, a page at a time, oldest first, each with its document |
| `POST /v1/pipeline/tasks/{task_id}/resolve` | resolve a manual parse with the analyst's transcript, or a triage with the analyst's decision (relevant with a type, or irrelevant); audited as `pipeline.task.resolve` |
| `POST /v1/pipeline/tasks/{task_id}/dismiss` | dismiss a task with the reason; audited as `pipeline.task.dismiss` |

An upload-only source (an `upload` adapter type, the statutes) lists nothing: the schedule never
crawls it and a fetch of it is a 409 `pipeline-source-upload-only`; `listable` says which sources
are. The spec is `packages/contracts/openapi/pipeline.v1.json` (`make openapi SERVICE=pipeline`).

## Manual parse and uploads

**Uploads.** `POST /v1/pipeline/sources/{key}/uploads` takes `multipart/form-data`: `file`, a PDF
or an HTML page, and the fields `actor_id`, `reason`, `title`, `published_on`, `external_ref` and
`document_type` (the source's type when left out; recorded on the document when given). The body
is refused before it is parsed once it passes `CW_PIPELINE_UPLOAD_MAX_BYTES` (25 MB by default)
and room for the fields (413 `pipeline-upload-too-large`), and a file whose bytes are not a PDF
or a page is a 415 `pipeline-upload-unsupported`. The bytes go to the raw store with no
transaction open; the document is recorded at `upload://<source key>/<sha256>` with its
`document.discovered` and the audit row in one transaction; then the ingest of the stored
document starts (`pipeline-upload-<key>-<id>`, `TemporalIngests`), which parses and classifies it
([Classification and triage](#classification-and-triage)) and, while
`CW_PIPELINE_KNOWLEDGE_ENABLED` is on, registers it unless the classification set it aside or
holds it for a triage. Bytes stored before are a duplicate: nothing is recorded again and the
ingest runs again. When Temporal does not answer the upload is a 503
`pipeline-ingest-unavailable` and the document stays stored: upload it again.

**Tasks.** Migration 0003's `pipeline_task` holds the work people do on stored documents. A
`manual_parse` task opens when no parser reads a document: the ingest sets it `failed` and nothing
of it is registered. A `triage` task opens when the classify step finds a conflict
([Classification and triage](#classification-and-triage)): the document waits, unregistered, for
a person's decision. A document has at most one open task of a kind. A task records why it opened (`reason`, each parser's), who
claims it, who resolved or dismissed it and when, what the resolution did (`resolution`) and the
note they gave. A parse that later succeeds closes the document's open manual parse itself (no
person in `resolved_by`).

**A transcript.** `POST /v1/pipeline/tasks/{task_id}/resolve` takes `transcript`, the document
typed by hand in the shape the table-aware parsers read documents into (`domain/transcripts.py`):

```json
{
  "title": "Example notification",
  "blocks": [
    {"type": "heading", "text": "Example heading", "page": 1},
    {"type": "paragraph", "number": "1.", "text": "Example text of the first paragraph."},
    {"type": "table", "header": ["S. No.", "Item"], "rows": [["1", "Example item"]]}
  ]
}
```

It is checked first (shape, empty text, at most 2,000 clauses of at most 50,000 characters, the
rulebook's limits), with each problem named by its place (`blocks[2].rows[0] has no text in any
cell`); a manual parse without one is a 422. The transcript is kept in the raw store as its
canonical JSON; the task is resolved with the transcript's key, digest, parser (`manual@1`) and
clause count, and audited; then the ingest of the stored document starts with the transcript
(`pipeline-manual-parse-<task>`), which parses it as `manual@1`, records the transcript on the
document, classifies it and, while knowledge is on, registers it unless the classification set
it aside or holds it for a triage. From then on the document is parsed from its transcript. When the ingest could not start the task stays resolved and the same request starts
it; a resolved task takes no other transcript (409 `pipeline-task-closed`).
`POST /v1/pipeline/tasks/{task_id}/dismiss` closes a task with the reason; a dismissed manual
parse leaves its document failed and unregistered, a dismissed triage leaves it held for triage
and unregistered.

The app reports `pipeline_open_tasks{kind}` and `pipeline_task_oldest_open_age_seconds{kind}`
(how long the oldest open task of each kind has waited) while telemetry is on.
`ParseFailureQueueHigh` opens a ticket when more than 20 manual parses have been open for 30
minutes ([docs/runbooks/parse-failures.md](../../docs/runbooks/parse-failures.md)), and
`TriageQueueStale` when the oldest triage task has waited more than 24 hours, for an hour
([docs/runbooks/pipeline-triage.md](../../docs/runbooks/pipeline-triage.md)).

## Classification and triage

After its parse, the ingest classifies every stored document (`pipeline.classify_document`,
`application/classify.py`). The detector (`application/detector.py`, no model) reads the opening
of the document, its title and first clauses read once, and gives:

- the **type** the opening names first (a press release by what one says of itself, an act
  amendment by an Act and its year with an amendment, a circular or a notification by its name),
  and the **confidence** of it: `certain` when that is the type its source publishes, `default`
  when the opening names no type and the source's is taken, `conflict` when it names another.
  A type a person gave (an uploader's `document_type`, a triage's) is taken as it is, `certain`,
  and so is a statute source's: an Act or the Rules quote notifications throughout. "On the
  recommendations of the Council", which nearly every notification says, does not make a press
  release;
- the **relevance**: `irrelevant` for a title that reads as a portal user manual or a how-to
  guide (an FAQ explains the law and stays relevant), else `relevant`;
- the **reasons**, in words, the type's first.

In one transaction the classification is recorded (`document_classification`, one row per
document), the document's status moves on and `document.classified` 1.0.0 is written; a conflict
also opens its `triage` task, whose reason is the classifier's. Where the document goes:

| Classification | Status (its route) | Then |
| --- | --- | --- |
| irrelevant (whatever its type) | `irrelevant` | the ingest ends; nothing is registered |
| relevant, `conflict` | `triage` | the ingest ends, unregistered, until a person decides |
| a press release or a statute | `reference` | registered and embedded while knowledge is on, nothing extracted |
| a notification, circular or act amendment | `classified` | registered as that type while knowledge is on, then its rule candidate is extracted while the extraction is on; `extracted` once an extraction is stored, an `unparseable` one too |

A status is the route the document was sent, set when it is classified and before anything is
registered, not what became of it. A `reference` or `classified` document keeps its status
whether or not knowledge is on and its registration succeeded (the ingest's result says
`registered`); a `classified` one stays so while the extraction is off or after it failed; and
`extracted` says an extraction is stored, whatever its `outcome` (`rule_extraction`), so a
document the model gave no candidate for is `extracted` too.

A document classified before keeps its classification: a second ingest of the same bytes, a
triage's continuation and a retry from the parse or the extract stage find it and write nothing.
A retry from the classify stage has the detector read the document again (`fresh`, behind the
patch `pipeline-reclassify-v1`): a reading that differs replaces the detector's earlier one, with
the status, a `document.classified` and, for a conflict, a triage task. A person's decision (a
triage's, a type given on a retry) is never read again. A type an admin gives on a retry
([Operations](#operations)) is the document's classification from then on: relevant, of that
type, `certain`, classifier `retry`, the admin in `decided_by`, written with the status and a
`document.classified` in the retry's transaction. It is the way back for a document the detector
set aside or whose triage was dismissed. A triage is resolved through
`POST /v1/pipeline/tasks/{task_id}/resolve` with `triage`:

```json
{"actor_id": "...", "reason": "Read the text: it clarifies the law", "triage": {"relevance": "relevant", "doc_type": "circular"}}
{"actor_id": "...", "reason": "A portal manual, not a regulator's notice", "triage": {"relevance": "irrelevant"}}
```

The decision is stored on the task's resolution (`relevance`, `doc_type`, the route it gives)
and becomes the document's classification (`certain`, classifier `triage`, the analyst in
`decided_by`), with its status and a second `document.classified`, audited as
`pipeline.task.resolve`, in one transaction. The stored raw document's own `doc_type` (the
uploader's) is never changed: the guard trigger keeps it. A relevant document then continues
through an ingest of the stored document (`pipeline-triage-<task>`), which finds the decision,
registers the document as the decided type while knowledge is on, and extracts its candidate
while the extraction is on; an irrelevant one is set aside and nothing starts. The same decision
again replays it and starts that ingest if it did not start (503 when Temporal does not answer),
also when two requests send it at once: the second finds the task resolved once it holds its row
lock, writes nothing and answers 200 like the first. Another decision is a 409. A relevant
triage needs a type and an irrelevant one takes none (422).

## Operations

The regulatory team's view of the whole pipeline, with the source manager's access (composition
class admin: the internal listener, and the public one in `token` mode only). The reads need a
regulatory role (analyst, reviewer or admin) a token names; the writes an admin, or in `header`
and `dual` mode the shared write token, and each names its actor and a reason of ten characters
or more and writes its `audit.event` row, of no tenant, in the transaction of the change. The
admin screen `admin.pipeline` (`apps/web/src/shared/config/screens.ts`) is ready for them; no UI
reads them yet.

| Route | What |
| --- | --- |
| `GET /v1/pipeline/runs` | every source's crawl runs, the latest started first, a page at a time (`limit`, `cursor`), of a `source_key`, a `status` (`running`, `completed`, `failed`) and a `trigger` (`schedule`, `manual`, `backfill`): each run's counts, error, trigger and workflow id (null on runs recorded before migration 0005) |
| `GET /v1/pipeline/documents` | every source's documents, the latest first fetch first, of a `status`, a `source_key`, a `doc_type` and publication dates (`published_from`, `published_to`, which leave undated documents out); each with `read_as` (its classification's type, else its uploader's, else its source's), its classification and its extraction by the current prompt |
| `GET /v1/pipeline/documents/{document_id}` | one document as above, with the retries people asked for |
| `POST /v1/pipeline/documents/{document_id}/retry` | `{actor_id, reason, stage, doc_type?}` with an `Idempotency-Key`: run the stored document again from a stage, without a new fetch; 202 with the attempt and its ingest's workflow id; audited as `pipeline.document.retry` |
| `GET /v1/pipeline/outbox/dead` | the outbox's dead rows, the newest dead first, of a `topic`: topic, key, attempts, last error, when it went dead and a summary of the payload (document, source, candidate, type) without its body |
| `POST /v1/pipeline/outbox/{event_id}/requeue` | `{actor_id, reason}`: a dead row back to pending (attempts reset, due at once, `last_error` kept until a send succeeds); `requeued: false` and nothing written for a row that is not dead; audited as `pipeline.outbox.requeue` |

**A retry** (`application/operations.py`, `domain/retry.py`) runs the ingest of the stored bytes
again under `pipeline-retry-<document>-<attempt>`, the attempt counted per document from 1:

- `stage: parse` is the whole ingest as an upload's runs it: parse (a document no parser read
  before is parsed again, which closes its manual parse when a parser added since reads it),
  classify (a classification stands), register while knowledge is on, and extract a
  notification, circular or act amendment while the extraction is on;
- `stage: classify` is the same with the detector reading the document again (`fresh`); a
  person's decision stands;
- `stage: extract` is for a document classified on its way to the extraction whose extraction
  failed or never started: 409 `pipeline-retry-refused` when it is not on its way to the
  extraction or one is stored for the current prompt, 422 `pipeline-retry-invalid` for a type no
  rule is extracted from.

A `doc_type` reclassifies the document first, whatever the stage: relevant, of that type,
`certain`, classifier `retry`, the admin in `decided_by` ([Classification and
triage](#classification-and-triage)). It beats the detector, and it is the way back for a
document set aside as irrelevant or whose triage was dismissed: a typed re-upload of the same
bytes is a duplicate and changes nothing. The attempt, the classification and the audit row are
written in one transaction with the document's row locked; the ingest starts once it closed. The
same request again under its `Idempotency-Key` answers its attempt (`Idempotent-Replayed: true`)
and starts its ingest only if it did not start (503 when Temporal did not answer: send it again);
the key with another body is a 422, a request without one a 428. A retry is refused with 409
`pipeline-ingest-running` while an ingest of the document runs (its earlier retries', its
crawl's, its tasks' resolutions' and its rule extraction's, the ids that follow from the
document; an upload's ingest has an id of its own that the check does not see), and with 409
`pipeline-retry-refused` while a triage task holds the document (decide or dismiss the task
first).

**A dead row** is one the relay gave up on after eight failed sends; its message is also on
`<topic>.dlq`. Requeue it once the cause is fixed, and the relay sends it on its next pass and
marks it published. A message a consumer gave up on is on `<topic>.<group>.dlq` instead:
`make replay` lists that topic and sends a message back to its origin
([docs/runbooks/outbox-relay.md](../../docs/runbooks/outbox-relay.md)).

**The classified backlog.** The documents the ingest classified while the extraction was off wait
as `classified`; turning the flag on extracts only what is classified from then on.
`pipeline-extract-backlog` counts them per source, leaving out the ones extracted for the current
prompt, and starts the sweep `pipeline.extract_backlog` on the worker, which runs each one's
extraction as a child, three at a time (`--concurrency`, 10 at most), under the id the ingest's
own extraction would have, so nothing is extracted twice. At most `--limit` documents (1,000 at
most) go into one sweep, the first fetched first; run it again for the rest. It refuses while
`CW_PIPELINE_EXTRACTION_ENABLED` is off; `--dry-run` only counts.

```bash
make extract-backlog ARGS="--dry-run"                               # per source, what waits
make extract-backlog ARGS="--source cbic_notifications --limit 200" # start one sweep
```

**The backfill** (`backfill.py`, `application/backfill.py`) fills the store with a regulator's
history through the crawl workflow, from a plan: `backfill-plan.yaml` lists, first, the
notifications the seed rules cite (`tests/unit/test_backfill_plan.py` keeps the list equal to the
seed calendar's), each in the window of the year its number names, then about 200 recent
notifications. A row names its source, `since`, and optionally `until`, the `refs` it takes (as
the listing writes them), `limit` (documents per crawl, 500 at most), `max_documents` and a
`note`; `--row N` runs only the Nth.

- `--dry-run` lists each row's window through its source's adapter and counts the documents new to
  the store and the ones it holds already; it fetches and writes nothing. **It reads the live
  regulator site**, so a person runs it; no test or check does.
- `--workflow --reason "<why>"` starts `pipeline.crawl_source` per row with the trigger `backfill`,
  the row's window and limit, on the running pipeline worker (task queue `pipeline`), waits for
  it, and crawls again while new documents are left (at most `--max-rounds`, 20); each crawl is a
  run with its `pipeline.source.backfill` audit row, naming `--actor-id` or the system's backfill.
  The worker fetches from the live sites, so the command refuses unless
  `CW_PIPELINE_CRAWL_ENABLED` is on in its own environment; the worker needs no flag for it (the
  flag also starts the worker's tick, which crawls every source at its cadence).
- `--report` counts per source, from the store, the documents stored, parsed, unread by any
  parser, set aside, waiting as classified, held for triage, kept for reference and extracted,
  with the current prompt's candidates and unparseable answers, and the share no parser read (more
  than 5% asks for OCR); then it asks the rulebook at `CW_RULEBOOK_URL`
  (`GET /v1/rulebook/review/stats`, `http://localhost:8003` by default) how analysts decided the
  candidates, and says so when the rulebook does not answer or refuses (in `token` mode the read
  wants an analyst's token). `--json` prints the dry run or the report as JSON.

The commands a person runs on the dev stack, which `make backfill` points at the local database's
`pipeline` schema (see [docs/runbooks/pipeline-backfill.md](../../docs/runbooks/pipeline-backfill.md)
before running them):

```bash
make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --dry-run"   # lists the live sites, fetches nothing
make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --report"    # the store, and the rulebook's acceptance
make worker SERVICE=pipeline   # another shell, unless a pipeline worker runs on the dev stack's Temporal
CW_PIPELINE_CRAWL_ENABLED=true make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --workflow --reason 'Backfill the notifications the seed rules cite'"
```

`--legacy` keeps the command this one replaced ([Sources](#sources)).

## The store

Migration 0001 creates the `pipeline` schema's tables, 0002 adds the sources' names and the
index the crawl looks known URLs up by (`source_key`, `source_url`), 0003 adds the parse of each
document and `pipeline_task`, and 0004 the statuses of a classified document,
`document_classification` and `rule_extraction`. They hold regulatory data, the same for every
tenant: no `tenant_id` and no row-level security, and `infra/scripts/migration_lint.toml` exempts
the six with the reason.

| Table | One row per | Columns |
| --- | --- | --- |
| `source` | source the pipeline reads | `key`, `name`, `adapter_type`, `parameters` (JSON), `cadence`, `enabled`, `paused`, `last_fetch_at`, `watermark` (JSON, `{"published_on": "2026-10-01"}`), `last_error`, `created_at`, `updated_at` |
| `raw_document` | fetched (or uploaded) file, by content | `id` (the first half of the SHA-256, checked by a constraint), `source_key`, `source_url`, `external_ref`, `fetched_at`, `published_on`, `content_type`, `size`, `sha256` (unique), `storage_key`, `title`, `status` (`discovered`, `parsed`, `failed`, `irrelevant`, `classified`, `triage`, `reference`, `extracted`), `parser_version` (the parser of its last parse, empty before one), `doc_type` (the type its uploader gave, null for its source's), `transcript_key` (the analyst's transcript it is parsed from) |
| `crawl_run` | crawl of one source | `id`, `source_key`, `started_at`, `finished_at`, `status` (`running`, `completed`, `failed`), the counts `listed`, `stored`, `duplicates`, `failed`, and `error` |
| `pipeline_task` | work a person does on a document | `id`, `kind` (`manual_parse`, `triage`), `document_id`, `source_key`, `status` (`open`, `resolved`, `dismissed`), `opened_at`, `reason`, `claimed_by`, `resolved_by`, `resolved_at`, `resolution` (JSON), `note`; at most one open task of a kind per document (`uq_pipeline_task_open`) |
| `document_classification` | classified document | `document_id`, `doc_type`, `relevance` (`relevant`, `irrelevant`), `confidence` (`certain`, `default`, `conflict`), `reasons` (JSON list), `classifier` (`detector@1`, or `triage` for a person's decision), `decided_by`, `task_id` (the triage task a conflict opened, or the one that decided it), `classified_at` |
| `rule_extraction` | document and extraction prompt version | `document_id`, `prompt_version`, `candidate_id` (derived from both), `outcome` (`extracted`, `unparseable`), `model`, `attempts`, `source_key`, `doc_type`, `regulator`, `fields` (the candidate in the extraction schema's shape, null when unparseable), `issues`, `citation_count`, `confidence`, `needs_review`, `answer` (the model's last answer, cut at 20,000 characters), `ontology_version`, `extracted_at`; kept as written (`pipeline_rule_extraction_guard`) |
| `outbox_event` | event to publish | py-common's outbox (ADR-005) |

A raw document never changes but for its status and its parse (`parser_version`,
`transcript_key`), and is never deleted: a trigger refuses the rest. The worker adds the built-in sources the table lacks when it starts (`SyncSources`, which
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
store's URI of the file. `document.parsed` 1.1.0 carries the document's type, title, language,
date, clause count and refs and the parser's name and version; the parse writes it when it
records a first parse, or a parse by another parser. The clause text is not in it: it is read
from the rulebook once the document is registered. `document.classified` 1.0.0 carries the
source's key, the type, relevance, confidence and reasons, the classifier, and the triage task
and the analyst when there are; `rule.candidate.created` 1.1.1 the candidate
([Extraction in the workflow](#extraction-in-the-workflow)). None has a tenant, and the outbox
keys all four by the source. The outbox relay publishes them: `make relay SERVICE=pipeline`, or
`cw-mvp worker`, which runs a relay for every schema with an outbox table while
`CW_WORKER_KAFKA_ENABLED` is on. The rulebook's candidate intake consumes
`rule.candidate.created` (group `rulebook.rule-candidates`, behind its own flag
`rulebook.candidate_intake`) and queues each candidate once for an analyst's review; nothing
consumes the other three yet.

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
| `cgst_act` (The Central Goods and Services Tax Act, 2017) | `upload`: `document_type` statute | never crawled | nothing: upload-only | nothing | statute |
| `cgst_rules` (The Central Goods and Services Tax Rules, 2017) | `upload`: `document_type` statute | never crawled | nothing: upload-only | nothing | statute |
| `igst_act` (The Integrated Goods and Services Tax Act, 2017) | `upload`: `document_type` statute | never crawled | nothing: upload-only | nothing | statute |

The `upload` type is not listable: it lists and fetches nothing, so the tick never crawls its
sources (`schedule.is_due` asks the adapter type), a fetch of one is refused, and no freshness
gauge is reported for one. It takes the `document_type` (statute by default) and the `regulator`
(CBIC by default) of what is uploaded. The statutes are its built-in sources: an analyst uploads
the Act or the Rules there (a PDF of the text, or an extract of the provisions the rules cite,
such as rules 61, 62, 80 and 138 of the CGST Rules), so the seed rules' citations can be checked
against stored clauses. A statute is registered and embedded but never extracted. The rulebook
takes at most 2,000 clauses of one document, so an Act or the Rules in full is uploaded in parts.

The CBIC type is one adapter for both portal listings: `listing` picks the API path and the
fields of its items, `category` the portal's category. A category is accepted only when its
listing is recorded under `tests/fixtures/cbic` (`cbic.RECORDED_CATEGORIES`), so another
category comes with its fixture. The cadences are what the crawl reads each source at, until an
admin changes them.

Every adapter goes through `PoliteClient`: the crawler user agent, `robots.txt` once per host,
one request per second per host (across the threads the activities fetch on), five tries with
exponential backoff on 5xx and transport errors. Source ids are UUID v5 of the key, so they are
the same in every environment.

Parsing goes through the parser chain ([The parser chain](#the-parser-chain)): a scanned PDF
raises `UnparsedDocumentError`, the ingest opens a manual-parse task for it, and the backfill
reports it as unparsed (OCR is a later parser). Clause references are `<language>.p<n>`; CBIC
gazette PDFs are bilingual and get `hi.` and `en.` clauses in one document. The detector
(`application/detector.py`) reads the title and the first clauses and returns the document type
with its confidence and the document's relevance ([Classification and
triage](#classification-and-triage)), the change kind (corrigendum, withdrawal, amendment,
extension or none), the canonical names of the notifications and circulars it cites (via
`domain_kernel.knowledge.normalise_name`), and whether the document is a press release
announcing something not yet in force.

The backfill goes through the crawl workflow from a plan ([Operations](#operations)). The command
it replaced stays behind `--legacy`, for recording fixtures: it fetches straight from a site into a
local raw store (`--store`, `var/raw`, under the same content keys, never overwritten), outside
the pipeline's store and its workflow, and records nothing:

```bash
make backfill ARGS="--legacy --source cbic_notifications --since 2026-01-01 --limit 5"
make backfill ARGS="--legacy --source gstcouncil_press --list-only"
```

The adapter tests replay `tests/fixtures/` through
`pipeline.testing.FixtureTransport`; nothing in the test suite reaches the network. The crawl's
tests use the test adapter type `recorded` (`pipeline.testing.RECORDED_TYPE`), which lists
recorded CBIC notifications from the recorded listings and fetches their recorded PDFs. What is
not done: OCR; a claim route for a task; events from the legacy backfill (it writes none, and it
classifies with the detector but records nothing); and adapters for the other states.

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

### Extraction in the workflow

`CW_PIPELINE_EXTRACTION_ENABLED` (flag `pipeline.extraction`, owner regulatory-intelligence,
default off) runs the extractor in the ingest (ADR-018, addendum of 2026-10-06). Once a
notification, circular or act amendment is classified and registered, the ingest starts the
child `pipeline.extract_rules` (`ExtractRulesWorkflow`, `workflows/extract_rules.py`) under
`pipeline-extract-<document>-extraction.rule_candidate-v1`, an id reused only after a failure,
and leaves it running (`ParentClosePolicy.ABANDON`, 45 days at most): neither the ingest nor a
crawl waits for a model. The ingest's result says `extraction`: `started`, `running` (an
extraction of that id runs or has completed), `off` (the worker's flag is off; the document waits
as `classified`) or `not_registered` (knowledge is off: the extraction reads the document from
the rulebook). The child has two activities (`application/extraction.py`):

1. `pipeline.extract_rules` reads the document as the rulebook keeps it, so every citation points
   at a stored clause, and asks the gateway with `extraction.rule_candidate@1`. An answer that is
   not a candidate (not JSON, not the schema's shape, or outside limits of the schema the parser
   does not check: a title or summary too long, no citation, a due month offset past 24) is asked
   for once more at temperature 0.3, which the gateway's cache of deterministic calls does not
   answer; two such answers are `unparseable`. It writes nothing and returns the answer as data.
   An extraction stored before for the document and the prompt version is returned as it is, and
   no model is asked;
2. `pipeline.store_extraction` stores the answer (`rule_extraction`) with its
   `rule.candidate.created` and the document's `extracted` status, in one transaction; an
   extraction stored before writes nothing. A failed write is retried without asking the model
   again.

A used-up budget does not fail the extraction: the gateway answers 429 with the problem type
`llm-budget-exceeded` and `Retry-After` until the budget resets, which the gateway client reads
as `ModelBudgetExhaustedError`; the activity hands it to the workflow without a retry, and the
workflow sleeps on a durable timer for the `Retry-After`, kept between 15 minutes and 6 hours (a
raised budget takes effect before the month ends), and asks again, at most 160 times. Any other
failure (a gateway or rulebook outage past six tries over some 15 minutes) fails the child; the
document stays `classified` until a re-ingest of it (an upload of the same bytes, say) finds its
classification and starts the extraction again, as a retry from the `extract` stage does
([Operations](#operations)). The documents that waited as `classified` while the flag was off are
not extracted by turning it on: `make extract-backlog` sweeps them. A backfill's crawls classify
and, with the flag on, extract like any other crawl.

`rule.candidate.created` 1.1 keeps the fields of 1.0.0 and adds `outcome`, `candidate` (the
model's candidate in `CANDIDATE_SCHEMA`'s shape, which the schema file keeps under `$defs`: a
contract test holds the two equal; null when unparseable), `issues`, `suggested_rule_key`,
`clause_ids` (the cited clauses' ids as the kernel derives them), `doc_type`, `source_id`,
`source_key` and `ontology_version`. The suggested rule key is `<form>_<cadence>`, as the seed
calendar names rules (`gstr3b_monthly`): the first GST form the obligation, title, summary or
quotes name, and the cadence of the recurrence, or of the filing scheme or return frequency the
candidate applies to; null without both. It is a suggestion for the analyst, never a lookup.

`make product` turns the extraction on only while its gateway answers from the fake model
(`CW_LLM_PROVIDER` unset or `fake`), and off with a real provider. The fake is deterministic, but
the gateway books each ask its cache did not answer at a tiny estimated price in its ledger (in
memory unless `CW_LLM_LEDGER=postgres` keeps it in the dev database). The product ingests nothing
by itself; the check's `extraction` step asks the gateway with the prompt only once its routing
table routes the extraction to fake models alone (`make product` routes it to `fake/echo` while
the provider is fake), and ingests nothing.
The workflow tests (`tests/integration/test_extraction_workflow.py`)
classify and extract the recorded 01/2026-Central Tax with a scripted model answering its draft
golden label, hold a synthetic circular for triage and extract it once triaged, keep a statute and a
press release for reference, and wait out a used-up budget;
`tools/demo/tests/unit/test_extraction_flow.py` runs the same through the one deployable's gateway.

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
make migrate SERVICE=pipeline     # source, raw_document, crawl_run, pipeline_task, outbox_event
make run SERVICE=pipeline           # http://localhost:8010/health, /ready, /v1/pipeline/sources
make worker SERVICE=pipeline      # the Temporal worker of the crawl and the ingest; with
                                  # CW_PIPELINE_CRAWL_ENABLED=true it crawls the live sites
make crawl-report ARGS="--days 30"  # the crawl per source and the F1 check
make extract-backlog ARGS="--dry-run"  # the documents waiting as classified, per source
make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --report"  # where a backfill got to
make relay SERVICE=pipeline       # publishes the pipeline's events from the outbox
make replay ARGS="list --topic rule.candidate.created.rulebook.rule-candidates.dlq"  # dead letters
make test                         # unit + contract tests with the coverage gate
docker build -f services/pipeline/Dockerfile -t compliancewatch-pipeline .
```

Package `pipeline`, dev port 8010, Postgres schema `pipeline`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

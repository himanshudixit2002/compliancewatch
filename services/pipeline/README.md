# pipeline service

Part of the ComplianceWatch monorepo. **Health routes, migrations wiring, one sample Temporal workflow, and the first source adapters: CBIC notifications and circulars, GST Council press releases, GSTN advisories, Maharashtra GST notifications, with PDF and HTML parsers, a change detector, a backfill command, the rule extractor with its validators behind the llm-gateway, and the labelling tool for the extraction golden set.**
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
  application/extractor.py # LlmRuleExtractor: one gateway call per document, then the validators
  application/validators.py # citations exist and quote the clause, numbers and dates are in the cited text, predicates fit the ontology
  domain/candidate.py      # CANDIDATE_SCHEMA (what the model returns, what a label looks like) and its parser
  domain/numbers.py        # every spelling of an amount or a date a regulator uses (two crore, 21st April, 2026)
  infrastructure/  # SQLAlchemy models, repositories, Kafka; fakes.py: in-memory adapter and parser
    http.py        # PoliteClient: user agent, robots.txt, per-host delay, retries
    raw_store.py   # content-addressed raw file store (local disk; memory for tests)
    adapters/      # one SourceAdapter per regulator site; registry.py: keys, ids, doc types
    parsers/       # PdfParser (pypdf text layer), HtmlParser, language detection, clause split
  workflows/       # Temporal workflows; ingest_document.py: discover, fetch, parse, register
  application/knowledge_activities.py  # RegisterDocument: hand the parsed document to the rulebook
  domain/knowledge.py, domain/ports.py # DocumentRecord and the KnowledgeSink port
  infrastructure/rulebook_client.py    # HttpRulebook: the rulebook's write API as a KnowledgeSink
  settings.py      # PipelineSettings: CW_PIPELINE_KNOWLEDGE_ENABLED, CW_RULEBOOK_URL, CW_RULEBOOK_WRITE_TOKEN
  backfill.py      # pipeline-backfill: list, fetch, store, parse and detect from the command line
  embed.py         # pipeline-embed: embed the stored clauses that have no vector yet
  application/embedding.py  # EmbeddingStage: unembedded clauses to the gateway, vectors to the rulebook
  domain/embedding.py       # embedding_text: the clause with its context header
  label.py         # pipeline-label: index, prepare and check golden extraction cases (make label)
  infrastructure/gateway.py  # GatewayProvider: the llm-gateway as the kernel's LLMProvider; GatewayEmbedder
  infrastructure/prompts.py  # loads prompts/<name>.v<version>.md; the registry holds its digest
prompts/           # extraction.rule_candidate.v1.md (owner regulatory-intelligence)
  testing.py       # FixtureTransport (replays tests/fixtures), ScriptedProvider, ScriptedEmbedder, MemoryRulebook
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

With `IngestRequest(knowledge=True, regulator="CBIC")` and `CW_PIPELINE_KNOWLEDGE_ENABLED=true`
the workflow runs a fourth activity, `pipeline.register_document`: it parses the fetched bytes
again and stores the document and its clauses in the rulebook through
`PUT /v1/rulebook/documents/{id}` (ADR-018), then checks that the rulebook answered with the clause
ids the kernel derives. The step sits behind `workflow.patched("kag-register-v1")`, so histories
recorded before it replay unchanged. The flag is off by default (owner regulatory-intelligence;
it goes when ADR-017 is accepted); off, the activity answers `skipped` without a call. With the
flag on, the request must name the regulator. A registration that fails (a refused write, a
rulebook outage longer than the retries) does not fail the ingest: the result says
`registered=False` with the reason in `registration_error`. A different parse of stored bytes,
which a parser change can cause, is refused and never retried; the stored clauses stay, since
mentions and citations point into them. Bump the parser's `PARSER_VERSION` with any change that
can alter clause text, so the refusal names both versions; what to do with stored documents
after such a change is an open decision (ADR-018). Deploy the rulebook before the pipeline.

## Knowledge extraction (KAG phase 2, ADR-017)

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
`CW_RULEBOOK_WRITE_TOKEN` and `CW_LLM_GATEWAY_URL`.

```bash
uv run --package compliancewatch-pipeline pipeline-embed --limit 500
uv run --package compliancewatch-pipeline pipeline-embed --model voyage/voyage-3.5-lite
```

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
make migrate SERVICE=pipeline
make run SERVICE=pipeline           # http://localhost:8010/health, /ready, /v1/pipeline/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/pipeline/Dockerfile -t compliancewatch-pipeline .
```

Package `pipeline`, dev port 8010, Postgres schema `pipeline`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

# rulebook service

Part of the ComplianceWatch monorepo. Health routes, alembic wiring, regulator documents and
clauses with a write and read API, the knowledge schema with entity alignment, the entity review
queue and relation candidates with their review API, the rule tables with the seed calendar, and
a read API over rule versions, entities, relations and clauses for the Q&A service, a hybrid
clause search index (full text and pgvector), and the citation, review and publish flow with its
rule events written through the transactional outbox (behind `CW_RULEBOOK_PUBLISH_ENABLED`).
Design reference: Project Foundation guide, sections 7, 8, 9 and 14; Architecture Reference 3.2, 5.2 and 6.2; ADR-017 and ADR-018.

- **Owns:** Rules, RuleVersions, Documents, Clauses, Citations, embeddings; versioning, supersession graph, hybrid search index, as-of queries;
  the knowledge tables `canonical_entity`, `clause_entity` and `rule_relation` (aligned entities,
  clause mentions, typed relations between rule versions and entities)
- **Owning team:** Regulatory Intelligence
- **Consumes:** parsed documents from the pipeline over `PUT /v1/rulebook/documents/{id}` (ADR-018); rule.published; rulebook read API (served to the engine, Q&A and review service)
- **Emits / publishes:** rule.published, rule.superseded, rule.withdrawn and rule.deadline_changed
  through `outbox_event` (ADR-005); no service consumes them yet

## What is in the database today

Migrations `0001` to `0007` create fourteen tables in schema `rulebook`:

| Table | Purpose | Keys |
| --- | --- | --- |
| `document` | A regulator document, one row per distinct file: source, digest, regulator, type, URL, title, language, parser version, publication and fetch time | pk `id` = first 32 hex digits of `sha256` (CHECK); unique `sha256`; append-only (trigger) |
| `clause` | The clauses of a document in order, verbatim as parsed, with `search_vector`, a stored generated `to_tsvector('english', text)` | pk `id` = `clause_id_for(document id, clause_ref)`; unique (`document_id`, `clause_ref`) and (`document_id`, `ordinal`); fk `document_id`; GIN index on `search_vector`; append-only (trigger) |
| `clause_embedding` | One clause's embedding from one model: `embedding vector(512)` (the kernel's `EMBEDDING_DIMS`) | pk (`clause_id`, `model`); fk `clause_id`; HNSW index for cosine distance; never updated (trigger), a new model means a new row |
| `citation` | A rule version's quote of a clause, with a one-way verification (`verified`, `match_score >= 0.85`, `verified_at`) | pk `id`; fks to `rule_version` and `clause`; identity columns fixed by trigger |
| `canonical_entity` | One row per aligned entity: `type` (ten values), `canonical_name`, `aliases text[]` (normalised names) | pk `id`; unique (`type`, `canonical_name`); GIN index on `aliases` |
| `clause_entity` | A mention of an entity in a clause with its half-open code-point span, and who found it (`method`: grammar, model or analyst; `extractor`) | pk (`clause_id`, `entity_id`, `span_start`); fks to `clause` and `canonical_entity` (restrict) |
| `rule_relation` | A typed relation (`supersedes`, `amends`, `refers_to`, `exempts`, `extends_deadline`, `corrects`, `withdraws`) from a rule version to a rule version (`to_rule_version_id`) or an entity (`to_entity_id`), with the evidence clause | pk `id`; unique (`from_rule_version_id`, `relation`, `to_kind`, `to_ref`, `clause_id`); fks to `rule_version`, `clause` and `canonical_entity` (restrict); CHECKs `ck_rule_relation_pairing`, `ck_rule_relation_target_entity`, `ck_rule_relation_target_version`, `ck_rule_relation_not_self` |
| `rule`, `rule_version` | Rules and their versions: status, effective period, predicates, obligation template, recurrence, seed provenance, `high_impact` and `submitted_at` (the start of the review round) | see migration 0003; the guard trigger of 0007 |
| `rule_version_decision` | The review and publication audit: submitted, returned, approved, published, withdrawn or superseded, by an analyst (`actor_id`) or caused by another version | pk `id`; fks to `rule_version` (both `rule_version_id` and `caused_by_rule_version_id`); CHECK that one of the two is set; append-only (trigger) |
| `outbox_event` | py-common's transactional outbox: the rule events, written in the transaction of the change they describe and relayed to Kafka | see `py_common.outbox.schema` |
| `extraction_run` | One run of an extraction stage over a document: counts and run-level issues, including model output that could not become a candidate | pk `id` (derived from document, stage, extractor); fk `document_id` |
| `entity_review` | A mention alignment could not resolve, with the reason (`no_match`, `ambiguous_alias`, `empty_name`, `unqualified`) and the analyst's decision | pk `id` (derived from clause, type, start); unique (`clause_id`, `entity_type`, `span_start`); CHECK that a decision is complete; partial index on open groups |
| `relation_candidate` | A relation the model proposed before any rule version exists: target as named (and aligned entity), evidence clause and quote, confidence, issues, period and new due date for extensions, status | pk `id` (derived from document, relation, target, evidence clause); fks to `document`, `clause`, `canonical_entity`, `rule`; CHECKs on scores, quote length, decision |

The vocabulary in the CHECK constraints is derived from the kernel (`EntityType`, `RelationKind`,
`RULE_VERSION_KIND`, `DocumentType`, `PARSER_VERSION_PATTERN`). The CHECKs on `rule_relation`
repeat the kernel's rules: `supersedes`, `extends_deadline`, `corrects` and `withdraws` target a
rule version; `to_entity_id` is set exactly when `to_kind` is an entity type, `to_rule_version_id`
exactly when it is `rule_version` (and then `to_ref` is its id); `to_ref` is never the source rule
version. Table names are unqualified: the connection's `search_path` puts them in `rulebook`.

Migration 0004 adds foreign keys to `clause_entity` and `rule_relation` and stops with a clear
message if either table has rows (nothing writes them before it).

Migration 0007 puts `rulebook_rule_version_guard` on `rule_version` (BEFORE UPDATE): the status
moves only along the kernel's `RULE_VERSION_TRANSITIONS` (draft to in_review, in_review to
approved, in_review or approved back to draft, approved to published, published to superseded or
withdrawn); once a
version is published, superseded or withdrawn its content is frozen and `effective_to` may only
be set or moved earlier; and approved to published needs `published_at`, at least one verified
citation and no unverified one, and one distinct approver in `rule_version_decision` since
`submitted_at`, two when `high_impact`. A writer that bypasses the use cases is held to the same
rules. `tests/unit/test_models_vocabulary.py` pins the trigger's literal pairs to the kernel.

## API

| Route | What it does |
| --- | --- |
| `PUT /v1/rulebook/documents/{document_id}` | Store a parsed document and its clauses. Needs `x-cw-write-token`. 201 when stored now, 200 when the same parse was stored already (with `metadata_differs` naming fields that differ; the stored row wins), 409 for a different parse of stored bytes, 422 when the id is not the digest's first half |
| `GET /v1/rulebook/documents/{document_id}` | The document with its clauses in order and their ids |
| `PUT /v1/rulebook/documents/{document_id}/mentions` | Align the mentions an extractor found: each is checked against the stored clause text at its span and must carry a canonical name; resolved ones go to `clause_entity`, the rest to `entity_review`. Needs the token |
| `PUT /v1/rulebook/documents/{document_id}/relation-candidates` | Stage the relations a run proposed, with the run's issues; idempotent per proposal. Needs the token |
| `GET /v1/rulebook/review/entities` | Open review groups, one per (entity type, proposed name), with up to five examples |
| `GET /v1/rulebook/review/entities/items` | Every open mention of one group with its review id |
| `POST /v1/rulebook/review/entities/decisions` | Create the entity, add the name to an existing one, or reject the group; resolves every open mention of the group and points open candidates at the entity. A name that does not name one entity across documents (empty, or a section or rule without its statute) is decided mention by mention: the decision lists the `review_ids` it covers and adds no alias. Needs the token |
| `GET /v1/rulebook/review/relations` | Relation candidates, open ones by default |
| `POST /v1/rulebook/review/relations/{id}/approve` | Approve into a `rule_relation` from a draft rule version (and to the target version for supersedes, extends_deadline, corrects, withdraws); 409 `rulebook-rule-version-not-editable` when the version is not a draft; refuses supersession cycles. Needs the token |
| `POST /v1/rulebook/review/relations/{id}/reject` | Reject with a reason. Needs the token |
| `GET /v1/rulebook/rules` | Rule keys with their latest title, the list the relation prompt may choose a rule from |
| `GET /v1/rulebook/rule-versions?as_of=&rule_key=&regulator=&limit=&after=` | Versions in force on `as_of`: published or superseded, with `effective_from <= as_of < effective_to`; ordered by rule key, paged with `after` (a rule key) |
| `GET /v1/rulebook/rule-versions/{id}` | One version in any status, with its citations |
| `GET /v1/rulebook/rule-versions/{id}/citations` | The clauses a version cites, with the quote and its verification |
| `GET /v1/rulebook/entities/resolve?type=&name=` | Normalise the name and resolve it the way alignment does. Always 200 with `status`: `resolved` (with the entity), `ambiguous` (with the candidates sharing the alias), `not_found`, `unqualified` (a section or rule without its statute) or `empty` |
| `GET /v1/rulebook/entities/{id}` | An entity with its aliases |
| `GET /v1/rulebook/entities/{id}/clauses?as_of=&limit=` | Clauses that mention the entity with the spans, newest document first (undated last); `as_of` keeps documents published on or before it |
| `GET /v1/rulebook/relations?from_rule_version_id=&to_rule_version_id=&to_entity_id=&relation=&published_only=&limit=` | Rule relations by either end (at least one id, else 422), with the evidence clause ref and document and, for a deadline extension, the candidate's period and new due date. `published_only` (default true) keeps relations from versions that have been published |
| `PUT /v1/rulebook/clauses/embeddings` | Store clause vectors from one model: `{model, dims: 512, items: [{clause_id, vector}]}` (1 to 256 items); returns `{stored, unchanged}`. A clause keeps its first embedding per model. A wrong `dims` is 422 `rulebook-embedding-dimension`, an unknown clause 422. Needs the token |
| `GET /v1/rulebook/clauses/unembedded?model=&document_id=&limit=&after=` | Clauses with no embedding from `model`, in clause id order, with their document's metadata (for the embedding text) |
| `POST /v1/rulebook/search` | Hybrid search, see below |
| `GET /v1/rulebook/clauses/{id}` | A clause with its document's regulator, type, reference, title, URL, language and date; 404 `rulebook-clause-unknown` when no clause has the id |
| `PUT /v1/rulebook/rule-versions/{id}/citations` | Cite clauses for a draft version (409 `rulebook-rule-version-not-editable` otherwise): `{citations: [{clause_id, quote}]}` (1 to 50). Every quote must match its clause (`quote_match_ratio >= 0.85`) and carry no number, form code or month name the clause lacks, else 422 `rulebook-citation-not-verified` and nothing is stored. Returns `{added, unchanged, citations}`; a citation's id derives from version, clause and quote. Needs the token |
| `POST /v1/rulebook/rule-versions/{id}/submit` | Draft to in_review: `{actor_id, high_impact?, note?}`. Starts a new approval round; a high-impact tag, once set, stays. Needs the token |
| `POST /v1/rulebook/rule-versions/{id}/return` | In_review or approved back to draft: `{actor_id, note?}`. The round's approvals no longer count and the seed status is needs_review again; the next submission starts a new round. Needs the token |
| `POST /v1/rulebook/rule-versions/{id}/approve` | One approval: `{actor_id, note?}`. The one that completes the round (one approver, two different ones when high impact) moves the version to approved and its seed status to reviewed; the same approver twice is 409 `rulebook-duplicate-approver`. Needs the token |
| `POST /v1/rulebook/rule-versions/{id}/publish` | Approved to published, applying the version's relations and writing the rule events; see below. `{actor_id, note?}`. Needs the token and the flag |
| `POST /v1/rulebook/rule-versions/{id}/withdraw` | Published to withdrawn with `rule.withdrawn` (no withdrawing version, effective today); 409 `rulebook-replacements-pending` while a version it replaces has not moved yet. Needs the token and the flag |
| `POST /v1/rulebook/maintenance/transitions` | The daily sweep, `{as_of?}` (today in India when empty, never later); returns the versions it moved and the events. Needs the token and the flag |

Nothing is aligned by fuzzy matching and nothing is created without an analyst (ADR-017). With
telemetry on, the service reports the gauges `rulebook_entity_review_open_items{entity_type}` and
`rulebook_entity_review_oldest_open_age_seconds` (read at most once a minute), and two ticket
alerts watch the queue: `EntityReviewQueueStale` when the oldest open item has waited more than
48 hours, and `EntityReviewQueueBacklog` when more than 500 items stay open for 6 hours
(`docs/runbooks/entity-review-queue.md`).

The read routes need no token. A superseded version stays in force for the dates before its
replacement took effect, so a question about a past date is answered from the version in force
then.

Writes fail closed: without `CW_RULEBOOK_WRITE_TOKEN` every write is a 503, and a missing or wrong
token is a 401. Publishing, withdrawing and the sweep also need `CW_RULEBOOK_PUBLISH_ENABLED=true`
(default off, 503 `rulebook-publishing-disabled`); citing and review work without it. The spec is committed at `packages/contracts/openapi/rulebook.v1.json`
(`make openapi SERVICE=rulebook`) and pinned by `tests/contract/test_openapi.py`.
`CW_RULEBOOK_STORE=memory` runs the service without a database (tests and demos).

## Search

`POST /v1/rulebook/search` takes `{text, vector?, model?, regulator?, doc_types[], as_of?, k}`
(`k` 1 to 50, default 8; a `vector` needs the `model` that embedded it, else 422). Two legs each
draw a pool of `min(200, max(40, 4k))` clauses:

- **Lexical:** the terms of `plainto_tsquery('english', text)` joined by OR against
  `clause.search_vector`, ranked by `ts_rank_cd`. Text with no searchable term (only stop words)
  skips this leg.
- **Vector:** cosine distance to the clauses embedded by the same `model`, over the HNSW index with
  `hnsw.ef_search = 100` and pgvector's iterative scan, so the filters still leave enough rows.

Reciprocal rank fusion (`1 / (60 + rank)` summed over the legs, ties by clause id) keeps the `k`
best. The filters apply to both legs: `regulator`, `doc_types`, and `as_of`, which keeps documents
published on or before it (undated documents are left out then). Each hit carries the clause,
its document's regulator, type, number (`external_ref`), title and date, `score`, `lexical_rank`
and `vector_rank` (null when the leg did not find it) and `cited_by`: the published or
superseded versions citing the clause with a verified quote, in force on `as_of` when it is
given. The rulebook never calls a model: the writer of `PUT /clauses/embeddings` and the reader
sending a query vector both embed through the LLM gateway.

## Publish lifecycle

A version goes draft, in_review, approved, published (ADR-006): cite its clauses, submit it,
approve it (one approver; two different ones when `high_impact`), publish it. Citations and
relations are added only while the version is a draft, so the round approves exactly what is
published; to change them, return the version (under review or approved) to draft, which starts
a new round. Every step is one transaction that locks the version, checks the move against the
kernel's transition table and appends a row to `rule_version_decision`; the kernel's
`InvalidTransitionError` is a 409. Citing and approving a relation lock the version the same way
before checking that it is a draft, so neither slips in beside a submission. Days are days in
India: "today" is the date in Asia/Kolkata when the step runs.

Publishing checks, in order (`rulebook.domain.publication.plan_publication`):

1. The version is approved.
2. It has at least one citation and every citation is verified (409 `rulebook-citations-missing`).
3. It has the approvals it needs in the current round (409 `rulebook-approvals-missing`).
4. Each relation from it to another version (X to Y, ADR-017) can take effect:
   - `supersedes`, `corrects` and `withdraws` replace Y. Y must be published (409
     `rulebook-relation-target-state`), start before X (409 `rulebook-replacement-dates`) and not
     be replaced by another published version (409 `rulebook-target-already-replaced`).
     Publication cuts Y's `effective_to` to X's `effective_from` at once. When X's
     `effective_from` is today or earlier, Y moves now (to superseded, or withdrawn for
     `withdraws`) and `rule.superseded` or `rule.withdrawn` goes out with the publication;
     otherwise Y stays published until the sweep moves it on X's first day. `corrects` is a
     replacement until a candidate can carry the corrected date.
   - `extends_deadline` sends `rule.deadline_changed` (reason `deadline_extended`) at
     publication, with the candidate's `new_due_on`, and its `period_label` when Y recurs (409
     `rulebook-deadline-detail-missing` without them). Y must be published or superseded.
5. Once cut, X overlaps no other version of its rule in force (409 `rulebook-overlapping-version`).

`rule.published` lists the targets of X's `supersedes` relations, the approvers and the ontology
attributes the predicates reference. The events of one publication share a correlation id, the
follow-on events name `rule.published` as their cause, every rule event has no tenant and the
rule id as its Kafka key, and all of them are written to `outbox_event` in the publication's
transaction; `python -m py_common.outbox` relays them. Nothing consumes the events yet; the
obligation service's consumer is still to be built.

A version cannot be withdrawn while a version it supersedes, corrects or withdraws is still
published (409 `rulebook-replacements-pending`): that version was cut at publication and moves
only when the replacement takes effect, so withdrawing the replacement first would leave it cut
for good. A mistaken publication dated in the future is corrected by publishing a new version
that corrects or supersedes it, not by withdrawing it before it takes effect.

The sweep moves every published version whose replacement's `effective_from` has come, earliest
replacement first, with its event and a decision naming the replacing version, and cuts its
`effective_to` to that date when it still ends later. It is idempotent:

```bash
CW_RULEBOOK_PUBLISH_ENABLED=true CW_DATABASE_URL=... uv run --package compliancewatch-rulebook rulebook-transitions [--as-of YYYY-MM-DD]
```

`POST /v1/rulebook/maintenance/transitions` runs the same sweep. With the flag off the command
prints that nothing moved and exits 0. Seed rules are never published by a migration or the seed
command; only this flow publishes.

## Seed calendar

`seed/gst_calendar.yaml` holds the standing GST obligations as draft rule versions: thirteen
rules (monthly and quarterly GSTR-1 and GSTR-3B, CMP-08, GSTR-4, GSTR-9, GSTR-9C, ITC-04
half-yearly and yearly, e-invoicing, e-way bills), each with a predicate tree over ontology
0.2.0 attributes, an obligation template, a recurrence where the duty repeats, the cited
instrument and reference, `seed_status: needs_review` and the questions an analyst answers
before publication. Nothing in the seed reaches a business until a version is published
through the review flow.

```bash
make seed SERVICE=rulebook ARGS=--check   # validate the file against the packaged ontology
make seed SERVICE=rulebook                # write draft versions into rule and rule_version
```

The command is idempotent: a re-run after editing the file updates the draft version in
place; a version that has left draft is never modified and a changed rule gets a new draft
version instead (`rulebook.infrastructure.seed_repository`). `rulebook.application.seed_loader`
parses and checks the file; `rulebook.domain.seed` is the value object. Tests replay the
calendar against sample profiles (a monthly filer, a QRMP filer in each state group, a
composition taxpayer) and check every due date the recurrences produce.

## Layout

```
src/rulebook/
  api/             # routers (documents, review, rule_versions, publication, graph, search), request/response schemas, the write-token dependency
  application/     # use cases: documents.py, alignment.py, review.py, relations.py, rule_versions.py, publication.py, graph.py, search.py; seed_loader.py
  domain/          # documents.py, alignment.py, review.py, relations.py, rule_versions.py, publication.py (the planner), events.py, graph.py, search.py, runs.py, ids.py, errors.py, repository.py, seed.py
  infrastructure/  # models.py (with the Vector column type), knowledge_repository.py (Postgres unit of work and outbox sink), memory.py, seed_repository.py, review_metrics.py (the review queue gauges)
  settings.py      # RulebookSettings: CW_RULEBOOK_STORE, CW_RULEBOOK_WRITE_TOKEN, CW_RULEBOOK_PUBLISH_ENABLED
  testing.py       # rulebook_settings() for tests and demos: memory store, known token
  wiring.py        # what the api layer gets from the composition root
  seed.py          # rulebook-seed command
  transitions.py   # rulebook-transitions command (the daily sweep)
  main.py          # composition root: build_app(settings), store selection, problem statuses, the review queue gauges when telemetry is on
seed/gst_calendar.yaml   # the seed calendar
migrations/        # alembic; env.py reads CW_DATABASE_URL and CW_DB_SCHEMA and targets models.Base.metadata
  versions/20260928_0001_knowledge_schema.py   # hand-written, mirrors models.py
  versions/20260928_0002_relation_kinds.py     # seven relation kinds
  versions/20260928_0003_rule_tables.py        # rule and rule_version
  versions/20260928_0004_documents_clauses_citations.py   # documents, clauses, citations; knowledge FKs
  versions/20260928_0005_review_queue_relation_candidates.py   # extraction runs, entity review, relation candidates
  versions/20260929_0006_clause_search_index.py   # clause.search_vector, clause_embedding, pgvector in public
  versions/20260929_0007_publish_flow.py   # high_impact, submitted_at, rule_version_decision, the rule_version guard, outbox_event
tests/
  unit/            # domain, use cases and API on the memory store; test_models_vocabulary.py: model CHECKs against the kernel enums
  integration/     # testcontainers (pgvector image): migrations up, down and up; document tables and triggers; the Postgres unit of work and its reads; the search index; the publish guard, the outbox and the sweep
  contract/        # test_openapi.py: the served schema equals the committed spec; test_events.py: the rule events match their schemas
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=rulebook     # alembic upgrade head in schema rulebook
make run SERVICE=rulebook         # http://localhost:8003/health, /ready, /v1/rulebook/ping, /v1/rulebook/documents/{id}
make relay SERVICE=rulebook       # relays the rule events in outbox_event to Kafka
make test                         # unit + contract tests with the coverage gate
make py-test-integration          # testcontainers tests; needs Docker
uv run pytest services/rulebook/tests/integration -q -m integration   # this service only
docker build -f services/rulebook/Dockerfile -t compliancewatch-rulebook .
```

With Colima, export `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock` before the
integration tests: the testcontainers reaper mounts the daemon socket at its path inside the VM,
not the host path `~/.colima/default/docker.sock`.

Check the schema after `make migrate`:

```bash
docker compose exec -T postgres psql -U cw -d compliancewatch -Atc \
  "select table_name from information_schema.tables where table_schema='rulebook' order by 1"
# alembic_version, canonical_entity, citation, clause, clause_embedding, clause_entity, document,
# entity_review, extraction_run, outbox_event, relation_candidate, rule, rule_relation,
# rule_version, rule_version_decision
```

Roll back with `CW_DATABASE_URL=... CW_DB_SCHEMA=rulebook uv run --package compliancewatch-rulebook alembic -c services/rulebook/alembic.ini downgrade base`
(the URL `make migrate` builds, with `?options=-csearch_path%3Drulebook%2Cpublic`).

Package `rulebook`, dev port 8003, Postgres schema `rulebook`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

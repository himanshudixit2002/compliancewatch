# rulebook service

Part of the ComplianceWatch monorepo. Health routes, alembic wiring, regulator documents and
clauses with a write and read API, the knowledge schema with entity alignment, the entity review
queue and relation candidates with their review API, the rule tables with the seed calendar, and
data-quality checks over versions, citations and relations. No publish flow or rule read API for
the engine yet.
Design reference: Project Foundation guide, sections 7, 8, 9 and 14; Architecture Reference 3.2, 5.2 and 6.2; ADR-017 and ADR-018.

- **Owns:** Rules, RuleVersions, Documents, Clauses, Citations, embeddings; versioning, supersession graph, hybrid search index, as-of queries;
  the knowledge tables `canonical_entity`, `clause_entity` and `rule_relation` (aligned entities,
  clause mentions, typed relations between rule versions and entities)
- **Owning team:** Regulatory Intelligence
- **Consumes:** parsed documents from the pipeline over `PUT /v1/rulebook/documents/{id}` (ADR-018); rule.published; rulebook read API (served to the engine, Q&A and review service)
- **Emits / publishes:** rule.superseded (scheduled when effective dates pass)

## What is in the database today

Migrations `0001` to `0005` create eleven tables in schema `rulebook`:

| Table | Purpose | Keys |
| --- | --- | --- |
| `document` | A regulator document, one row per distinct file: source, digest, regulator, type, URL, title, language, parser version, publication and fetch time | pk `id` = first 32 hex digits of `sha256` (CHECK); unique `sha256`; append-only (trigger) |
| `clause` | The clauses of a document in order, verbatim as parsed | pk `id` = `clause_id_for(document id, clause_ref)`; unique (`document_id`, `clause_ref`) and (`document_id`, `ordinal`); fk `document_id`; append-only (trigger) |
| `citation` | A rule version's quote of a clause, with a one-way verification (`verified`, `match_score >= 0.85`, `verified_at`) | pk `id`; fks to `rule_version` and `clause`; identity columns fixed by trigger |
| `canonical_entity` | One row per aligned entity: `type` (ten values), `canonical_name`, `aliases text[]` (normalised names) | pk `id`; unique (`type`, `canonical_name`); GIN index on `aliases` |
| `clause_entity` | A mention of an entity in a clause with its half-open code-point span, and who found it (`method`: grammar, model or analyst; `extractor`) | pk (`clause_id`, `entity_id`, `span_start`); fks to `clause` and `canonical_entity` (restrict) |
| `rule_relation` | A typed relation (`supersedes`, `amends`, `refers_to`, `exempts`, `extends_deadline`, `corrects`, `withdraws`) from a rule version to a rule version (`to_rule_version_id`) or an entity (`to_entity_id`), with the evidence clause | pk `id`; unique (`from_rule_version_id`, `relation`, `to_kind`, `to_ref`, `clause_id`); fks to `rule_version`, `clause` and `canonical_entity` (restrict); CHECKs `ck_rule_relation_pairing`, `ck_rule_relation_target_entity`, `ck_rule_relation_target_version`, `ck_rule_relation_not_self` |
| `rule`, `rule_version` | Rules and their versions: status, effective period, predicates, obligation template, recurrence, seed provenance | see migration 0003 |
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
| `POST /v1/rulebook/review/relations/{id}/approve` | Approve into a `rule_relation` from a rule version not yet published (and to the target version for supersedes, extends_deadline, corrects, withdraws); refuses supersession cycles. Needs the token |
| `POST /v1/rulebook/review/relations/{id}/reject` | Reject with a reason. Needs the token |
| `GET /v1/rulebook/rules` | Rule keys with their latest title, the list the relation prompt may choose a rule from |

Nothing is aligned by fuzzy matching and nothing is created without an analyst (ADR-017). The
queue has no alert yet: someone in Regulatory Intelligence has to watch it.

Writes fail closed: without `CW_RULEBOOK_WRITE_TOKEN` every write is a 503, and a missing or wrong
token is a 401. The spec is committed at `packages/contracts/openapi/rulebook.v1.json`
(`make openapi SERVICE=rulebook`) and pinned by `tests/contract/test_openapi.py`.
`CW_RULEBOOK_STORE=memory` runs the service without a database (tests and demos).

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

## Data quality

`rulebook-quality` (`make data-quality`, `ARGS=--json` for JSON) reads every rule version with
its citation counts and open analyst questions, and every relation between rule versions, in
one read-only transaction, and runs five checks (`rulebook.domain.quality`):

| Check | A violation is |
| --- | --- |
| `in_force_without_verified_citation` | a published or superseded version with no citation, or with a citation that is not verified (ADR-006) |
| `overlapping_in_force_periods` | two published or superseded versions of one rule whose half-open periods `[from, to)` overlap |
| `supersession_cycle` | a cycle over `supersedes` and `corrects` edges between rule versions |
| `unknown_predicate_attribute` | a version, other than a withdrawn one, whose specification names an attribute the ontology lacks or cannot be read; a free-text predicate may name a new attribute while the version carries an open analyst question (`todo`), as the seed's ITC-04 rules do |
| `effective_dates_disordered` | `effective_to` on or before `effective_from` (also refused by `ck_rule_version_effective`) |

It prints each check with up to 10 samples and exits 1 on any violation, 0 when clean and 2 when
the database cannot be read. `make data-quality` reads the local stack's `rulebook` schema, or
`CW_DQ_DATABASE_URL` when that is set. The nightly workflow runs it on a fresh Postgres with the
migrations and the seed calendar, or on a deployed database through the repository secret
`CW_DQ_DATABASE_URL`; a failure opens or updates the nightly issue with the label
`data-quality`. What to do about a violation: `docs/runbooks/rulebook-data-quality.md`.

## Layout

```
src/rulebook/
  api/             # routers (documents), request/response schemas, the write-token dependency
  application/     # use cases: documents.py, alignment.py, review.py, relations.py; seed_loader.py
  domain/          # documents.py, alignment.py, review.py, relations.py, runs.py, ids.py, errors.py, repository.py, seed.py
  infrastructure/  # models.py, knowledge_repository.py (Postgres unit of work), memory.py, seed_repository.py
  settings.py      # RulebookSettings: CW_RULEBOOK_STORE, CW_RULEBOOK_WRITE_TOKEN
  testing.py       # rulebook_settings() for tests and demos: memory store, known token
  wiring.py        # what the api layer gets from the composition root
  seed.py          # rulebook-seed command
  quality.py       # rulebook-quality command: domain/quality.py checks, application/quality.py, infrastructure/quality_reader.py
  main.py          # composition root: build_app(settings), store selection, problem statuses
seed/gst_calendar.yaml   # the seed calendar
migrations/        # alembic; env.py reads CW_DATABASE_URL and CW_DB_SCHEMA and targets models.Base.metadata
  versions/20260928_0001_knowledge_schema.py   # hand-written, mirrors models.py
  versions/20260928_0002_relation_kinds.py     # seven relation kinds
  versions/20260928_0003_rule_tables.py        # rule and rule_version
  versions/20260928_0004_documents_clauses_citations.py   # documents, clauses, citations; knowledge FKs
  versions/20260928_0005_review_queue_relation_candidates.py   # extraction runs, entity review, relation candidates
tests/
  unit/            # domain, use cases and API on the memory store; test_models_vocabulary.py: model CHECKs against the kernel enums
  integration/     # testcontainers (pgvector image): migrations up, down and up; document tables and triggers; the Postgres unit of work
  contract/        # test_openapi.py: the served schema equals the committed spec
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=rulebook     # alembic upgrade head in schema rulebook
make run SERVICE=rulebook         # http://localhost:8003/health, /ready, /v1/rulebook/ping, /v1/rulebook/documents/{id}
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
# alembic_version, canonical_entity, citation, clause, clause_entity, document, entity_review,
# extraction_run, relation_candidate, rule, rule_relation, rule_version
```

Roll back with `CW_DATABASE_URL=... CW_DB_SCHEMA=rulebook uv run --package compliancewatch-rulebook alembic -c services/rulebook/alembic.ini downgrade base`
(the URL `make migrate` builds, with `?options=-csearch_path%3Drulebook%2Cpublic`).

Package `rulebook`, dev port 8003, Postgres schema `rulebook`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

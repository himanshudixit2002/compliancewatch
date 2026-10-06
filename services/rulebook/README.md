# rulebook service

Part of the ComplianceWatch monorepo. Health routes, alembic wiring, regulator documents and
clauses with a write and read API, the knowledge schema with entity alignment, the entity review
queue and relation candidates with their review API, the rule tables with the seed calendar, and
a read API over rule versions, entities, relations and clauses for the Q&A service, a hybrid
clause search index (full text and pgvector) whose hits say when their rule is out of force, and
the citation, review and publish flow (analyst actions behind their own review token, separate
from the pipeline's write token) with its rule events written through the transactional outbox
(behind `CW_RULEBOOK_PUBLISH_ENABLED`), review tasks (the queue analysts work the seed drafts
and the pipeline's rule candidates through, with the two-person rule), the candidate intake
(the worker's consumer of rule.candidate.created, behind `CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED`),
the public API's changes feed (`GET /v1/changes`) read back from the decision log, and
data-quality checks over versions, citations and relations.
Design reference: Project Foundation guide, sections 7, 8, 9 and 14; Architecture Reference 3.2, 5.2 and 6.2; ADR-017 and ADR-018.

- **Owns:** Rules, RuleVersions, Documents, Clauses, Citations, embeddings; versioning, supersession graph, hybrid search index, as-of queries;
  the knowledge tables `canonical_entity`, `clause_entity` and `rule_relation` (aligned entities,
  clause mentions, typed relations between rule versions and entities)
- **Owning team:** Regulatory Intelligence
- **Consumes:** parsed documents from the pipeline over `PUT /v1/rulebook/documents/{id}` (ADR-018); rule.candidate.created (the worker's group `rulebook.rule-candidates`, see Candidate intake); rulebook read API (served to the engine, Q&A and review service)
- **Emits / publishes:** rule.published, rule.superseded, rule.withdrawn and rule.deadline_changed
  through `outbox_event` (ADR-005); the applicability engine fans a publication out and cancels it
  on a withdrawal, and the obligation service acts on all four. rule.rejected when an analyst
  rejects a rule candidate; nothing consumes it yet

## What is in the database today

Migrations `0001` to `0007` create fourteen tables in schema `rulebook`, `0008` lets a document be a
statute, `0009` adds `review_task` and the `edited` decision, `0010` adds `rule_candidate`,
candidate review tasks, `rule_version.candidate_id` and the consumer inbox `processed_event`, and
`0011` ties a candidate's draft to its candidate and its task with composite foreign keys:

| Table | Purpose | Keys |
| --- | --- | --- |
| `document` | A regulator document, one row per distinct file: source, digest, regulator, type (`notification`, `circular`, `press_release`, `act_amendment` or `statute`, the last from migration 0008), URL, title, language, parser version, publication and fetch time | pk `id` = first 32 hex digits of `sha256` (CHECK); unique `sha256`; append-only (trigger) |
| `clause` | The clauses of a document in order, verbatim as parsed, with `search_vector`, a stored generated `to_tsvector('english', text)` | pk `id` = `clause_id_for(document id, clause_ref)`; unique (`document_id`, `clause_ref`) and (`document_id`, `ordinal`); fk `document_id`; GIN index on `search_vector`; append-only (trigger) |
| `clause_embedding` | One clause's embedding from one model: `embedding vector(512)` (the kernel's `EMBEDDING_DIMS`) | pk (`clause_id`, `model`); fk `clause_id`; HNSW index for cosine distance; never updated (trigger), a new model means a new row |
| `citation` | A rule version's quote of a clause, with a one-way verification (`verified`, `match_score >= 0.85`, `verified_at`) | pk `id`; fks to `rule_version` and `clause`; identity columns fixed by trigger |
| `canonical_entity` | One row per aligned entity: `type` (ten values), `canonical_name`, `aliases text[]` (normalised names) | pk `id`; unique (`type`, `canonical_name`); GIN index on `aliases` |
| `clause_entity` | A mention of an entity in a clause with its half-open code-point span, and who found it (`method`: grammar, model or analyst; `extractor`) | pk (`clause_id`, `entity_id`, `span_start`); fks to `clause` and `canonical_entity` (restrict) |
| `rule_relation` | A typed relation (`supersedes`, `amends`, `refers_to`, `exempts`, `extends_deadline`, `corrects`, `withdraws`) from a rule version to a rule version (`to_rule_version_id`) or an entity (`to_entity_id`), with the evidence clause | pk `id`; unique (`from_rule_version_id`, `relation`, `to_kind`, `to_ref`, `clause_id`); fks to `rule_version`, `clause` and `canonical_entity` (restrict); CHECKs `ck_rule_relation_pairing`, `ck_rule_relation_target_entity`, `ck_rule_relation_target_version`, `ck_rule_relation_not_self` |
| `rule`, `rule_version` | Rules and their versions: status, effective period, predicates, obligation template, recurrence, seed provenance, `high_impact` and `submitted_at` (the start of the review round), and `candidate_id`, the rule candidate a version was drafted from (migration 0010) | see migration 0003; the guard trigger of 0007; unique `candidate_id`, and unique (`id`, `candidate_id`), which 0011's keys reference |
| `rule_version_decision` | The review and publication audit: submitted, returned, approved, published, withdrawn or superseded, by an analyst (`actor_id`) or caused by another version, and `edited` (migration 0009): an analyst's change to a draft through its review task, with what changed in the note | pk `id`; fks to `rule_version` (both `rule_version_id` and `caused_by_rule_version_id`); CHECK that one of the two is set; append-only (trigger) |
| `review_task` | One decision (approve, return, reject) asked about one rule version or one rule candidate: `kind` (`seed`, or `candidate` from migration 0010), `priority`, the `regulator`, `status` (open, claimed, decided), who claimed it and when, who decided what and when, and the decision's note; a candidate task names its `candidate_id` and has no `rule_version_id` until the version is drafted | pk `id`; fks `rule_version_id` and `candidate_id`, and (`rule_version_id`, `candidate_id`) to `rule_version (id, candidate_id)` (0011), so a candidate task's version is the one drafted from its candidate; CHECKs that the state, claim and decision columns agree and that a seed task has its version and a candidate task its candidate; partial unique indexes: one task per version, and one per candidate, that is not decided; never deleted, a decided task never changes, and a task takes its version once (trigger) |
| `rule_candidate` | A rule candidate the pipeline extracted (rule.candidate.created), keyed by the event's `candidate_id`: its document, regulator (lower case), model, prompt version, confidence, citation count, whether it asked for review, the outcome (`extracted`, `unparseable`), the rest of the event in `payload` (the candidate itself, its issues, the cited clause ids, the type, the source, the ontology version), the suggested rule key, whether it looks high impact, the event it came with, and its review: `status` (open, drafted, approved, rejected), the version drafted from it, the reject reason, who decided and when | pk `id`; fks `document_id` and `rule_version_id` (unique), and (`rule_version_id`, `id`) to `rule_version (id, candidate_id)` (0011), so the version a candidate names was drafted from it; CHECKs that the regulator is lower case, the scores in range and the status, version, reason and decision agree |
| `outbox_event` | py-common's transactional outbox: the rule events and rule.rejected, written in the transaction of the change they describe and relayed to Kafka | see `py_common.outbox.schema` |
| `processed_event` | py-common's consumer inbox: the rule.candidate.created events the worker's group `rulebook.rule-candidates` took in, so a redelivered one is skipped | see `py_common.outbox.schema` |
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

Migration 0007 puts two triggers on `rule_version`. `rulebook_rule_version_insert_guard` (BEFORE
INSERT) admits only a draft with no `published_at`, so every published version went through the
review flow. `rulebook_rule_version_guard` (BEFORE UPDATE) does the rest: the status moves only
along the kernel's `RULE_VERSION_TRANSITIONS` (draft to in_review, in_review to approved,
in_review or approved back to draft, approved to published, published to superseded or
withdrawn); once a version is published, superseded or withdrawn its content is frozen and
`effective_to` may only be set or moved earlier; and approved to published needs `published_at`,
at least one verified citation and no unverified one, and one distinct approver in
`rule_version_decision` since `submitted_at`, two when `high_impact`. A writer that bypasses the
use cases is held to the same rules. `tests/unit/test_models_vocabulary.py` pins the trigger's
literal pairs to the kernel.

Migration 0009 puts `rulebook_review_task_guard` (BEFORE UPDATE OR DELETE) on `review_task`: a
decided task never changes, a task keeps its version, kind, regulator and opening time, and no
task is deleted. Its downgrade fails while an `edited` decision is recorded, since the audit is
append-only, rather than dropping it. Migration 0010 relaxes the guard for candidate tasks: a
task keeps its kind, candidate, regulator and opening time, and its version once it has one, so
a candidate task's `rule_version_id` goes from null to the drafted version once and never
changes after. The seed tasks stored before 0010 keep their versions and pass its checks; its
downgrade refuses, before it changes anything, while a rule candidate or a candidate task is
stored. Migration 0011 then ties the three places that name a candidate's draft together: a
candidate task's (`rule_version_id`, `candidate_id`) and a candidate's (`rule_version_id`, `id`)
reference `rule_version (id, candidate_id)`, so a task's version can only become the one drafted
from its own candidate, and a version's `candidate_id` cannot change while either names it.
MATCH SIMPLE leaves a seed task and a task or candidate not drafted yet unchecked, and drafting
writes in an order that holds at every statement, so the keys are not deferred.

## API

| Route | What it does |
| --- | --- |
| `PUT /v1/rulebook/documents/{document_id}` | Store a parsed document and its clauses. Needs `x-cw-write-token`. 201 when stored now, 200 when the same parse was stored already (with `metadata_differs` naming fields that differ; the stored row wins). The first parse is kept (ADR-018): a parse by another parser version (`parser_version`, such as `pdf-tables@1` or an analyst's `manual@1`) is answered 200 with the stored clauses' ids, the stored `parser_version` and `parser_version` among `metadata_differs`, and nothing is written; 409 for a different parse by the same parser version; 422 when the id is not the digest's first half |
| `GET /v1/rulebook/documents/{document_id}` | The document with its clauses in order and their ids |
| `PUT /v1/rulebook/documents/{document_id}/mentions` | Align the mentions an extractor found: each is checked against the stored clause text at its span and must carry a canonical name; resolved ones go to `clause_entity`, the rest to `entity_review`. Needs the write token |
| `PUT /v1/rulebook/documents/{document_id}/relation-candidates` | Stage the relations a run proposed, with the run's issues; idempotent per proposal. Needs the write token |
| `GET /v1/rulebook/review/entities` | Open review groups, one per (entity type, proposed name), with up to five examples |
| `GET /v1/rulebook/review/entities/items` | Every open mention of one group with its review id |
| `POST /v1/rulebook/review/entities/decisions` | Create the entity, add the name to an existing one, or reject the group; resolves every open mention of the group and points open candidates at the entity. A name that does not name one entity across documents (empty, or a section or rule without its statute) is decided mention by mention: the decision lists the `review_ids` it covers and adds no alias. Needs the review token |
| `GET /v1/rulebook/review/relations` | Relation candidates, open ones by default |
| `POST /v1/rulebook/review/relations/{id}/approve` | Approve into a `rule_relation` from a draft rule version (and to the target version for supersedes, extends_deadline, corrects, withdraws); 409 `rulebook-rule-version-not-editable` when the version is not a draft, 409 `rulebook-rule-version-closed` when it is a closed draft (its rule candidate was rejected); refuses supersession cycles. Needs the review token |
| `POST /v1/rulebook/review/relations/{id}/reject` | Reject with a reason. Needs the review token |
| `GET /v1/rulebook/rules` | Rule keys with their latest title, the list the relation prompt may choose a rule from. A closed draft (drafted from a rule candidate that was rejected) is never a rule's latest version, so its title is never listed, and a rule only closed drafts hold is left out |
| `GET /v1/rulebook/rules/{rule_key}/versions` | Every version of the rule in any status, by version number: the drafts the seed command writes as well as the versions past them, where a workbench finds the version to cite and submit. Each says whether it is `closed`, a draft whose rule candidate was rejected: it never moves on, so a reader after the rule's latest version (`cw-product publish`) skips it. 404 `rulebook-rule-not-found` for an unknown key |
| `GET /v1/rulebook/rule-versions?as_of=&rule_key=&regulator=&status=&limit=&after=&after_version=` | Versions in force on `as_of`: published or superseded, with `effective_from <= as_of < effective_to`. With `ended_on_or_after` instead of `as_of`, the versions whose `effective_to` is on or after that day, published or superseded, never withdrawn (withdrawing closes a version's obligations, so it governs nothing) and never open-ended: the applicability engine asks for the ones superseded since a day (`status=superseded`), whose returns may still be due. `status` keeps published or superseded ones. Ordered by rule key, then version; paged with `after` (a rule key) and `after_version` (a version of that rule key). Naming both days, or neither, is a 422 |
| `GET /v1/rulebook/rule-versions/{id}` | One version in any status, with its citations, `closed` (as in the listing above), `published_at` and `approved_by`: the distinct approvers of the review round it was published from (the decision audit's approvals since its `submitted_at`), empty until it is published, so a reader showing who reviewed a duty does not depend on having seen rule.published |
| `GET /v1/rulebook/rule-versions/{id}/citations` | The clauses a version cites, with the quote and its verification |
| `GET /v1/rulebook/entities/resolve?type=&name=` | Normalise the name and resolve it the way alignment does. Always 200 with `status`: `resolved` (with the entity), `ambiguous` (with the candidates sharing the alias), `not_found`, `unqualified` (a section or rule without its statute) or `empty` |
| `GET /v1/rulebook/entities/{id}` | An entity with its aliases |
| `GET /v1/rulebook/entities/{id}/clauses?as_of=&limit=` | Clauses that mention the entity with the spans, newest document first (undated last); `as_of` keeps documents published on or before it, and `out_of_force` says whether the clause's rule is out of force then (see Search) |
| `GET /v1/rulebook/relations?from_rule_version_id=&to_rule_version_id=&to_entity_id=&relation=&published_only=&limit=` | Rule relations by either end (at least one id, else 422), with the evidence clause ref and document and, for a deadline extension, the candidate's period and new due date. `published_only` (default true) keeps relations from versions that have been published |
| `PUT /v1/rulebook/clauses/embeddings` | Store clause vectors from one model: `{model, dims: 512, items: [{clause_id, vector}]}` (1 to 256 items); returns `{stored, unchanged}`. A clause keeps its first embedding per model. A wrong `dims` is 422 `rulebook-embedding-dimension`, an unknown clause 422. Needs the write token |
| `GET /v1/rulebook/clauses/unembedded?model=&document_id=&limit=&after=` | Clauses with no embedding from `model`, in clause id order, with their document's metadata (for the embedding text) |
| `POST /v1/rulebook/search` | Hybrid search, see below |
| `GET /v1/rulebook/clauses/{id}` | A clause with its document's regulator, type, reference, title, URL, language and date; 404 `rulebook-clause-unknown` when no clause has the id |
| `PUT /v1/rulebook/rule-versions/{id}/citations` | Cite clauses for a draft version (409 `rulebook-rule-version-not-editable` otherwise, 409 `rulebook-rule-version-closed` for a closed draft): `{citations: [{clause_id, quote}]}` (1 to 50). Every quote must match its clause (`quote_match_ratio >= 0.85`) and carry no number, form code or month name the clause lacks, else 422 `rulebook-citation-not-verified` and nothing is stored. Returns `{added, unchanged, citations}`; a citation's id derives from version, clause and quote. Needs the review token |
| `POST /v1/rulebook/rule-versions/{id}/submit` | Draft to in_review: `{actor_id, high_impact?, note?}`. Starts a new approval round; a high-impact tag, once set, stays. A closed draft is never submitted (409 `rulebook-rule-version-closed`), nor approved or published. Needs the review token |
| `POST /v1/rulebook/rule-versions/{id}/return` | In_review or approved back to draft: `{actor_id, note?}`. The round's approvals no longer count and the seed status is needs_review again; the next submission starts a new round. Needs the review token |
| `POST /v1/rulebook/rule-versions/{id}/approve` | One approval: `{actor_id, note?, synthetic?}`. The one that completes the round (one approver, two different ones when high impact) moves the version to approved and its seed status to reviewed; the same approver twice is 409 `rulebook-duplicate-approver`. `synthetic: true` marks an approval no analyst made, the local product's demo publication (`cw-product`): it counts towards the round, but a round it completes leaves the seed status at needs_review, and it is refused with 403 `rulebook-synthetic-approval-refused` unless `CW_ENV` is local or test. Needs the review token |
| `POST /v1/rulebook/rule-versions/{id}/publish` | Approved to published, applying the version's relations and writing the rule events; see below. `{actor_id, note?}`. Needs the review token and the flag |
| `POST /v1/rulebook/rule-versions/{id}/withdraw` | Published to withdrawn with `rule.withdrawn` (no withdrawing version, effective today); 409 `rulebook-replacements-pending` while a version it replaces has not moved yet. Needs the review token and the flag |
| `POST /v1/rulebook/maintenance/transitions` | The daily sweep, `{as_of?}` (today in India when empty, never later); returns the versions it moved and the events. Needs the review token and the flag |
| `GET /v1/rulebook/review/tasks?status=&regulator=&kind=&limit=&cursor=` | The review queue: by regulator, higher priority first, then oldest first, a page of `limit` (1 to 200, 50) with a keyset cursor; each task with its version's rule key, number, title and status, whether it is high impact and the approvals of its current round. `kind` keeps `seed` or `candidate` tasks; `regulator` is compared in lower case. A candidate task not drafted yet shows its candidate's title and suggested rule key, null version fields and the suggested impact; `candidate` summarises the candidate of every candidate task. See Review tasks below |
| `POST /v1/rulebook/review/tasks/seed` | Opens a task of kind `seed` for every draft that needs review and has no task open or claimed; a second request opens none. Needs the review token |
| `GET /v1/rulebook/review/tasks/{task_id}` | The task with its version (content, the specification described line by line, the citations with their verification, the documents they cite, the approvers of its current round), the source's link when there is one, and the history: the version's decision audit and every task it has had. A candidate task also carries `candidate`: the extraction as stored, its document (`document_id` for the pipeline's `GET /v1/pipeline/documents/{document_id}/raw`), the draft it proposes and what does not map, why it looks high impact and whether a rule has its suggested key; until it is drafted its `rule_version` is null |
| `POST /v1/rulebook/review/tasks/{task_id}/draft` | `{actor_id, rule_key, new_rule?: {regulator, level}, edits?, citations?, relation_candidates?: [{candidate_id, target_rule_version_id?}], note?}`: the claimant of a candidate task drafts a version from its candidate, once (409 `rulebook-candidate-already-drafted`): the next version of `rule_key`'s rule, or the first of a new rule with `new_rule` (422 `rulebook-rule-key-unknown` without it, 409 `rulebook-rule-key-taken` with it for a key a rule has), always of the candidate's regulator, numbered past every version the rule has (a closed draft's too). Content from the candidate with `edits` applied, checked as the seed calendar is (422 `rulebook-draft-incomplete` with every problem, nothing stored); the candidate's quotes, or `citations`, verified (422 `rulebook-citation-not-verified`); the relation candidates listed, of the candidate's document, approved onto the draft. Returns the task as `GET` does. Needs the review token, or an analyst's access token |
| `POST /v1/rulebook/review/tasks/{task_id}/claim` | `{actor_id}`: the analyst takes the task; the claimant claiming again changes nothing; 409 `rulebook-review-task-claimed` when someone else holds it, `rulebook-review-task-closed` when it was decided. Needs the review token |
| `PATCH /v1/rulebook/review/tasks/{task_id}/draft` | `{actor_id, note?, title?, summary?, specification?, obligation_template?, recurrence?, effective_from?, effective_to?, todo?, citations?}`: the claimant edits the draft's content and cites clauses in one transaction; 409 `rulebook-review-task-not-claimed` for anyone else, `rulebook-rule-version-not-editable` past draft and `rulebook-candidate-not-drafted` for a candidate task with no draft yet; every quote is verified as `PUT .../citations` verifies it (422 `rulebook-citation-not-verified`, nothing stored). Recorded as an `edited` decision. Returns the task as `GET` does. Needs the review token |
| `POST /v1/rulebook/review/tasks/{task_id}/decide` | `{actor_id, decision, note?, high_impact?, reason?}`: `approve`, `return` or `reject`, with the version's transition in the same transaction; a return or a rejection needs a note, and a candidate task's rejection a `reason` (`not_a_rule`, `wrong_extraction`, `duplicate`, `out_of_scope`, `unparseable`). A candidate task not drafted yet can only be rejected (409 `rulebook-candidate-not-drafted`). A rejection after drafting closes the draft and opens again the relation candidates approved onto it, their rule relations deleted. Returns the task, the version's lifecycle (null for a candidate rejected before drafting), the task a return opened, the candidate's status and the events written (rule.rejected). Needs the review token |
| `GET /v1/rulebook/review/stats` | Tasks by status and by regulator, the decisions made, the median time from opening to decision, when the oldest task not decided yet was opened and its age, and `candidates`: the candidates decided, approved (and how many of those without an edit), rejected, and the acceptance rate, approved without edits over decided |
| `GET /v1/changes?since=&regulator=&limit=&cursor=` | The public API's changes feed: one item per published change, newest first, `limit` 1 to 100 (50) with a keyset cursor; see Changes feed below |

Nothing is aligned by fuzzy matching and nothing is created without an analyst (ADR-017). With
telemetry on, the service reports the gauges `rulebook_entity_review_open_items{entity_type}` and
`rulebook_entity_review_oldest_open_age_seconds` (read at most once a minute), and two ticket
alerts watch the queue: `EntityReviewQueueStale` when the oldest open item has waited more than
48 hours, and `EntityReviewQueueBacklog` when more than 500 items stay open for 6 hours
(`docs/runbooks/entity-review-queue.md`). The review tasks have their own gauges,
`rulebook_review_tasks_open{regulator}` (tasks not decided yet, claimed or not) and
`rulebook_review_task_oldest_open_age_seconds`, and the ticket alert `RuleReviewQueueStale` fires
when the oldest task not decided has waited more than 48 hours, for an hour
(`docs/runbooks/rule-review-queue.md`).

The read routes need no token. A superseded version stays in force for the dates before its
replacement took effect, so a question about a past date is answered from the version in force
then.

Two shared secrets guard the writes, and each fails closed. The pipeline's writes (documents,
mentions, relation candidates, clause embeddings) need `CW_RULEBOOK_WRITE_TOKEN` in
`x-cw-write-token`: without it configured they are a 503 `rulebook-writes-disabled`, and a missing
or wrong token is a 401 `rulebook-write-token-invalid`. An analyst's actions (entity review
decisions, relation approvals and rejections, citations, submit, return, approve, publish,
withdraw, the sweep, and the review tasks' seed, claim, draft, draft edit and decision) need
`CW_RULEBOOK_REVIEW_TOKEN` in `x-cw-review-token` instead: 503
`rulebook-reviews-disabled` without it, 401 `rulebook-review-token-invalid` for a missing or wrong
one. The write token does not open the analyst's routes, so a leaked pipeline secret cannot
approve or publish a rule; give the two different values. The review token is still a shared
secret, not an identity: the `actor_id` and `decided_by` in the bodies are asserted by the caller
(see Authentication below for access tokens, which name the actor). Publishing, withdrawing and
the sweep also need
`CW_RULEBOOK_PUBLISH_ENABLED=true` (default off, 503 `rulebook-publishing-disabled`); citing and
review work without it. The spec is committed at `packages/contracts/openapi/rulebook.v1.json`
(`make openapi SERVICE=rulebook`) and pinned by `tests/contract/test_openapi.py`.
`CW_RULEBOOK_STORE=memory` runs the service without a database (tests and demos); with
`CW_RULEBOOK_SEED_ON_START=true` (local and test only) it starts with the seed calendar's drafts.

### Authentication

The caller comes from `py_common.auth` by `CW_AUTH_MODE` (`api/deps.py`), and every write is one
of two kinds. `PipelineWrite` (documents, mentions, relation candidates, clause embeddings) takes a
service token with `rulebook:write`. `AnalystWrite` takes a signed-in user with the route's roles:

| Routes | Roles (or scope) |
| --- | --- |
| entity review decisions, relation approvals and rejections, the sweep | `analyst`, `reviewer` or `admin` |
| `PUT .../citations`, `POST .../submit` | `analyst`, or a service with `rulebook:write` |
| `POST .../return` | `analyst` or `reviewer`, or a service with `rulebook:write` |
| `POST .../approve`, `.../publish`, `.../withdraw` | `reviewer` |
| `POST .../review/tasks/{id}/claim`, `PATCH .../review/tasks/{id}/draft` | `analyst` |
| `POST .../review/tasks/{id}/decide`, `POST .../review/tasks/seed` | `analyst`, `reviewer` or `admin` |

- `header` (the default): no token is read; the two shared tokens guard the writes as above.
- `dual`: a request with a bearer token is served by its scope or roles, and one without it by
  the shared tokens. An unset shared token then asks for an access token (401
  `auth-token-required`) instead of answering 503.
- `token`: only a bearer opens the writes (401 `auth-token-required` without one); the shared
  tokens are refused.

A caller a token names but who lacks the role or scope is a 403 `auth-forbidden`, whatever shared
token it also sends. A signed-in user is recorded as who decided a review (`decided_by`, their
user id) or took a step on a version (`actor_id`), and the body's value is ignored, so the two
approvals of a high-impact version come from two people; a service, which is no person, still
names the actor in the body. The review queues (`GET /v1/rulebook/review/entities`, `.../items`,
`GET /v1/rulebook/review/relations`, the review tasks, one task and `GET .../review/stats`) need
an `analyst`, `reviewer` or `admin` token in token mode, and such a token when a bearer is sent in
dual mode; without a token they stay open. The
rest of the read API, the changes feed included, needs no token in any mode. Sessions of regulatory
roles carry a second factor, which identity enforces when it issues them.
`tests/unit/test_auth_mode.py` covers the three modes, and `tests/unit/test_api_review_tasks.py`
the review tasks in each.

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
and `vector_rank` (null when the leg did not find it), `cited_by`: the published or
superseded versions citing the clause with a verified quote, in force on `as_of` when it is
given, and `out_of_force`: true when a published, superseded or withdrawn version cites the
clause with a verified quote and none of them is in force on `as_of` (false without `as_of` or
without such a citation). A superseded notification's text still matches a question about a
later date; `out_of_force` tells the reader that the rule it states no longer applies then. The
rulebook never calls a model: the writer of `PUT /clauses/embeddings` and the reader
sending a query vector both embed through the LLM gateway.

## Publish lifecycle

A version goes draft, in_review, approved, published (ADR-006): cite its clauses, submit it,
approve it (one approver; two different ones when `high_impact`), publish it. Citations and
relations are added only while the version is a draft, so the round approves exactly what is
published; to change them, return the version (under review or approved) to draft, which starts
a new round. Every step is one transaction that locks the version, checks the move against the
kernel's transition table and appends a row to `rule_version_decision`; the kernel's
`InvalidTransitionError` is a 409. A version drafted from a rule candidate that was rejected is
closed: no step cites it, relates from it, submits, approves or publishes it (409
`rulebook-rule-version-closed`), and it stays a draft. Citing and approving a relation lock the
version the same way before checking that it is a draft, so neither slips in beside a
submission. Days are days in India: "today" is the date in Asia/Kolkata when the step runs.

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
transaction; `python -m py_common.outbox` relays them. The applicability engine and the
obligation service consume them.

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

## Review tasks

A review task asks for one decision about one rule version: approve it, return it for rework, or
reject it (`rulebook.domain.review_tasks`, `rulebook.application.review_tasks`). A version has at
most one task that is not decided, and so has a rule candidate; a decided task never changes.
Two kinds share the queue:

- `seed`: `POST /v1/rulebook/review/tasks/seed` opens one for every seed draft that needs review
  (the seed calendar's thirteen, as `make seed SERVICE=rulebook` writes them) and has no task
  open or claimed. Seed tasks share priority 50 and the queue keeps them by regulator, then
  oldest first. A version drafted from a candidate never gets a seed task.
- `candidate`: the candidate intake opens one for every rule candidate the pipeline extracts
  (see Candidate intake), under the candidate's regulator in lower case and at its priority:
  100 when it looks high impact, 80 when there is no candidate to draft from (an analyst drafts
  it by hand), 50 when the extraction asked for review or a validator found an issue, 10
  otherwise. Until a version is drafted from it the task has no version: it can be claimed,
  drafted and rejected, nothing else (409 `rulebook-candidate-not-drafted`).

1. **Claim.** An analyst claims an open task; it stays theirs until a decision. Only the claimant
   drafts and edits, so two people never edit one draft at once.
2. **Draft (candidate tasks).** `POST .../draft` makes the version, once per candidate, in one
   transaction: the rule when the key is new (with its regulator, the candidate's, and its
   level; an unused key), then the next version of the rule as a draft that names the candidate
   (`rule_version.candidate_id`) and starts high impact when the candidate suggests it. Its
   content is what the candidate proposes (`intake.draft_content`: each `applies_to` condition a
   predicate of an `all_of`, the obligation a template, the recurrence and dates read as the
   kernel reads them; a condition the kernel refuses leaves the specification out rather than
   widen the rule) with the analyst's `edits` on top, checked as an edit is; whatever is missing,
   does not map or fails the checks comes back as 422 `rulebook-draft-incomplete` with every
   problem, and nothing is stored. The citations are the candidate's quotes (or the `citations`
   sent), verified against their clauses by the step `PUT .../citations` runs. The relation
   candidates the analyst lists, of the candidate's document, are approved onto the draft in the
   same transaction (`relations.approve_relation`, the core of `POST .../relations/{id}/approve`),
   so an `extends_deadline` reaches the publication. What the analyst changed from the candidate
   is one `edited` row of the decision audit, naming the dotted paths
   (`obligation_template.due_in_days`, `citations`); a candidate taken as it was records none.
   The candidate becomes `drafted` and the task keeps the version from then on.
3. **Edit.** `PATCH .../draft` changes the content (title, summary, specification, obligation
   template, recurrence, effective period, open questions) and cites clauses, in one
   transaction. The content is checked as the seed loader checks the calendar
   (`rulebook.domain.drafting`): structured predicates must fit the ontology, a free-text
   predicate may name an attribute the ontology lacks only while an open question stays in
   `todo`, and a duty that does not recur needs the template's `due_in_days`. Citations go through
   the step `PUT .../citations` runs (verified against the stored clause, all or nothing): an
   analyst uploads the statute a seed rule cites (`cgst_act`, `cgst_rules`, `igst_act` are
   upload-only pipeline sources), and once it is registered its clauses can be cited. Each edit
   is a row `edited` in the decision audit, by the analyst, naming what changed.
4. **Decide.** An analyst, a reviewer or an admin decides, and the version's transition commits
   in the same transaction as the decision (`add_citations`, `submit_for_review`,
   `approve_version` and `return_to_draft` in `application/publication.py` run inside the
   caller's unit of work; the publish routes run them in one of their own):
   - `approve` submits a draft (raising it to high impact when `high_impact` is sent; a tag,
     once set, stays) and approves it. The approvers of the round are counted from
     `rule_version_decision` alone, and the same person twice is 409
     `rulebook-duplicate-approver`. The approval that completes the round (one approver, two
     different ones for a high-impact version) approves the version, marks its seed status
     reviewed, decides the task and approves a candidate task's candidate; an earlier one leaves
     the task open, unclaimed, for a second reviewer.
   - `return` sends a version under review or approved back to draft (its round's approvals
     stop counting); a draft stays a draft. The task is decided and a new open task asks for the
     rework (a candidate task's names the candidate too).
   - `reject` closes the task and leaves the version a draft (a version under review or approved
     goes back to draft; one the publish routes moved on is left as it is). No task opens; the
     next seed request opens one for a rejected seed draft. A candidate task's rejection names a
     `reason` (`not_a_rule`, `wrong_extraction`, `duplicate`, `out_of_scope`, `unparseable`),
     rejects the candidate before or after drafting, and writes rule.rejected (the candidate,
     its document, regulator, reason, prompt version and model, and the version drafted from it
     when there is one) to the outbox in the same transaction. A draft made from a rejected
     candidate stays a draft, since no transition discards one, but it is closed
     (`intake.version_closed`): no step cites it, relates from it, submits, approves or publishes
     it (409 `rulebook-rule-version-closed`), and it is never its rule's latest version (the seed
     command and `GET /v1/rulebook/rules` skip it; the rule's next version is numbered past it).
     The relation candidates approved onto it are open again in the same transaction
     (`relations.reopen_relations`), their `rule_relation` rows deleted and a note on each
     saying why, so an `extends_deadline` reaches a corrected draft instead of being stranded.
     A version the publish routes published before the rejection stands, with its relations.
5. **Publish.** Approving never publishes. A reviewer publishes the approved version through
   `POST /v1/rulebook/rule-versions/{id}/publish`, as before, with its checks (verified
   citations, the round's approvers) and its events; the fan-out and the obligations follow, and
   an `extends_deadline` approved onto a candidate's draft writes rule.deadline_changed, which
   the obligation worker turns into rescheduled obligations.

Who acts is the user a verified token names, or in header and dual mode the body's `actor_id`
with the review token, as on the publish routes. The publish routes still work on a version that
has a task: a version they approve or publish outside the task leaves the task waiting, and a
rejection closes it. The seed command leaves alone a candidate's draft and a version an analyst
edited through its task, and updates its own draft beside a candidate's (see Seed calendar).
`GET .../review/stats` counts the decided candidates and the acceptance rate, approved without an
edit over decided, ADR-006's measure of the extraction.

## Candidate intake

The rulebook worker consumes rule.candidate.created in group `rulebook.rule-candidates` while
`CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED` is on (flag `rulebook.candidate_intake`, default off,
owner regulatory-intelligence) and `CW_WORKER_KAFKA_ENABLED` runs consumers. Each event becomes,
in the transaction that also records it in `processed_event`, one `rule_candidate` row and one
candidate review task (`IngestRuleCandidate`, `rulebook.application.intake`):

- the payload is checked against its contract (the generated `RuleCandidateCreatedV1`, then
  `CandidateIntake.from_payload`); a missing `outcome` is `extracted`;
- a candidate id stored before changes nothing, whatever event carried it;
- the candidate's document must be registered: an unknown one fails and is retried, then goes to
  `rule.candidate.created.rulebook.rule-candidates.dlq`, and a replay once the document is
  registered takes it in;
- the regulator is kept in lower case (the pipeline sends the source registry's `CBIC`);
- the suggested rule key is the payload's when a rule has that key, else the one rule key the
  document's relation candidates name when they name exactly one (an analyst's rejected ones left
  out), else the payload's as a key for a new rule. The pipeline's key is a `<form>_<cadence>`
  heuristic, never a lookup, and `GET .../review/tasks/{id}` says whether a rule has it
  (`suggested_rule_known`).

Nothing is drafted by the intake: an analyst drafts, as above. Off, no group reads the topic,
which keeps the candidates a month; turned on, the group reads them from the start. `make product`
leaves it off, so the product never writes candidates into the database it shares. A failed
extraction is run again by ingesting the stored document again (the pipeline's business).

## Changes feed

`GET /v1/changes` is a path of the public API (tag `public`) outside the service's prefix, the
same for every tenant: it needs no tenant and no token in any mode, like the rest of the read
API, and its `x-roles` name every tenant member role and the regulatory roles. It is read back
from `rule_version_decision` (`rulebook.domain.changes`), one item per change a rule event
announced:

| `kind` | From | About (`rule_version_id`) | `caused_by_rule_version_id` |
| --- | --- | --- | --- |
| `published` | a `published` decision | the version published | null |
| `superseded` | a `superseded` decision, at the replacement's publication or in the sweep | the version replaced | the replacing version |
| `withdrawn` | a `withdrawn` decision | the version withdrawn | the version that withdraws it, or null for an analyst's withdrawal |
| `deadline_changed` | a `published` decision, once per `extends_deadline` relation from that version to a version | the version whose due date moved; `deadline` has the period, the new due date and the evidence clause | the extending version |

Submissions, returns and approvals are not changes. Each item carries the version as it stands:
its rule key, title, summary, number, regulator, level, status, effective dates and `seed_status`
(needs_review until an analyst reviews it; a synthetic approval reviews nothing, so the web shows
a not-yet-reviewed notice), `approved_by` and `published_at` (the approvers of the round it was
published from, empty and null for a version never published), its verified citations (clause,
document, clause ref and quote) and `relations`, the versions it supersedes, corrects or
withdraws and the due dates it moves.

The feed is newest first, by `changed_at` (the decision's time) then `change_id`, both
descending, a page of `limit` (1 to 100, default 50) at a time with an opaque keyset `cursor`
(`py_common.pagination`'s format, scope `rulebook.changes`). A change's id is its decision's id;
a deadline change's is the first 32 hex digits of the SHA-256 of `<decision id>:<relation id>`,
which the Postgres store computes in SQL and the domain in Python, so every read gives a change
the same id. `since` keeps the changes at or after a moment: a date (from the start of that day
in India) or a date-time with its offset; `regulator` keeps the versions of one regulator's rules.
A page reads in one transaction: the changes, then each version's record, approvers, citations
and relations, once per version.

## Known limitations

- A withdrawn version is hidden from every date, including the dates before it was withdrawn:
  `GET /v1/rulebook/rule-versions?as_of=` never returns it, search leaves it out of `cited_by`,
  and a clause only it cites is `out_of_force` on every date. A question about a day when the
  version still applied is answered as if it never had. `GET /v1/rulebook/rule-versions/{id}`
  still reads it, with its dates, in any status.

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

The command is idempotent: a re-run after editing the file updates the seed's own draft in
place, the rule's latest version not drafted from a rule candidate, even with a candidate's draft
beside it; a version that has left draft is never modified and a changed rule gets a new draft
version instead (`rulebook.infrastructure.seed_repository`). The seed status that review sets to
reviewed is not compared, so re-running the seed after an approval adds nothing. A seed draft an
analyst edited through its review task (an `edited` decision), and a rule whose latest version an
analyst edited or drafted from a rule candidate (its `candidate_id`), are the analyst's: the
command neither overwrites that version nor adds one after it, and reports the rule as kept, so a
release that runs the seed never reverts an analyst's work. A closed draft (drafted from a rule
candidate that was rejected) is skipped as if it were not there, and a new version is numbered
past it. The command locks each rule's row before it reads its versions, as drafting from a
candidate does, so the two never take one version number: the second waits for the first. `rulebook.application.seed_loader`
parses and checks the file; `rulebook.domain.seed` is the value object.

A rulebook on the memory store has no database for the command to write into, so
`CW_RULEBOOK_SEED_ON_START=true` loads the same calendar into the memory store when the app is
built (`seed_memory_store` in `main.py`, through `MemoryKnowledgeStore.apply_seed`, which follows
the command's rules). Every version it loads is a draft that needs review; nothing is cited,
approved or published. It is a local and test convenience for the web app's `make web-stack`,
where analysts cite, submit and review the drafts: the setting is refused unless `CW_ENV` is
`local` or `test`, and refused with `CW_RULEBOOK_STORE=postgres`, which `make seed
SERVICE=rulebook` fills. It defaults to off and is configuration, not a rollout flag
(`NOT_FLAGS` in `infra/scripts/check_flags.py`). Tests replay the
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
`CW_DQ_DATABASE_URL`; either failing exit code opens or updates the nightly issue, and a
violation (exit code 1) also labels it `data-quality`. What to do about a violation:
`docs/runbooks/rulebook-data-quality.md`.

## Golden export

`rulebook-golden-export` (`make golden-export ARGS="--since 2026-10-01 --out var/golden-export"`)
reads the rule candidates analysts decided on or after a day and writes them as draft cases of
the extraction golden set (`application/golden_export.py`), for an analyst to review and copy into
`evals/golden/extraction/cases` by hand:

- An approved candidate is one case, `<out>/cases/<case id>.yaml`, in the shape
  `pipeline-label prepare` writes and the eval harness loads: `label_status: draft`,
  `labelled_by` the analyst who decided it, `reviewed_by` empty, the document's clauses as stored,
  and `expected` the approved version's content mapped back to the candidate shape (what the
  analyst corrected is in `export.edited`). The case id is the notification number's slug and the
  candidate id's last eight hex digits.
- A rejected candidate is listed in `<out>/summary.yaml` with its reason: the golden shape has no
  negative case.
- A candidate whose approved conditions the shape cannot hold (anything but an `all_of` of
  attribute, operator and value) is skipped, with why, in the summary.

It refuses an `--out` inside `evals/golden` (exit 2): only a person moves a case there, after
a review, and no exported case is ever marked reviewed. `ARGS` takes `--json` for the summary as
JSON; exit 1 when the database cannot be read. `make golden-export` reads the local stack's
`rulebook` schema. `packages/contracts/golden/extraction-case.example.yaml` is one exported case
from synthetic data: `tests/contract/test_golden_case_shape.py` checks the export against it and
the eval harness's `tests/unit/test_exported_case.py` loads it, so the two sides agree on the
shape without importing each other.

## Layout

```
src/rulebook/
  api/             # routers (documents, review, review_tasks, rule_versions, publication, graph, search; changes, the public GET /v1/changes), request/response schemas, the write-token and review-token dependencies
  application/     # use cases: documents.py, alignment.py, review.py, review_tasks.py (and drafting from a candidate), intake.py (the candidate intake), relations.py, rule_versions.py, publication.py, graph.py, search.py, changes.py, golden_export.py (decided candidates as draft golden cases); seed_loader.py
  domain/          # documents.py, alignment.py, review.py, review_tasks.py, intake.py (rule candidates and the draft they propose), drafting.py (the checks of a draft's content), relations.py, rule_versions.py, publication.py (the planner), events.py, graph.py, search.py, changes.py (the feed), runs.py, ids.py, errors.py, repository.py, seed.py
  infrastructure/  # models.py (with the Vector column type), knowledge_repository.py (Postgres unit of work and outbox sink), memory.py, seed_repository.py, review_metrics.py (the gauges of both review queues)
  settings.py      # RulebookSettings: CW_RULEBOOK_STORE, CW_RULEBOOK_WRITE_TOKEN, CW_RULEBOOK_REVIEW_TOKEN, CW_RULEBOOK_PUBLISH_ENABLED, CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED, CW_RULEBOOK_SEED_ON_START (local and test, memory store)
  worker.py        # python -m rulebook.worker: the daily transitions sweep and the consumer of rule.candidate.created
  testing.py       # rulebook_settings() for tests and demos: memory store, known tokens (WRITE_TOKEN, REVIEW_TOKEN)
  wiring.py        # what the api layer gets from the composition root
  seed.py          # rulebook-seed command
  quality.py       # rulebook-quality command: domain/quality.py checks, application/quality.py, infrastructure/quality_reader.py
  transitions.py   # rulebook-transitions command (the daily sweep)
  golden.py        # rulebook-golden-export command
  main.py          # composition root: build_app(settings), store selection, the seed calendar loaded at start when asked, problem statuses, the review queue gauges when telemetry is on
seed/gst_calendar.yaml   # the seed calendar
migrations/        # alembic; env.py reads CW_DATABASE_URL and CW_DB_SCHEMA and targets models.Base.metadata
  versions/20260928_0001_knowledge_schema.py   # hand-written, mirrors models.py
  versions/20260928_0002_relation_kinds.py     # seven relation kinds
  versions/20260928_0003_rule_tables.py        # rule and rule_version
  versions/20260928_0004_documents_clauses_citations.py   # documents, clauses, citations; knowledge FKs
  versions/20260928_0005_review_queue_relation_candidates.py   # extraction runs, entity review, relation candidates
  versions/20260929_0006_clause_search_index.py   # clause.search_vector, clause_embedding, pgvector in public
  versions/20260929_0007_publish_flow.py   # high_impact, submitted_at, rule_version_decision, the rule_version guard, outbox_event
  versions/20261006_0008_statute_document_type.py  # ck_document_doc_type admits statute
  versions/20261006_0009_review_tasks.py   # review_task with its guard; the edited decision
  versions/20261006_0010_rule_candidates.py   # rule_candidate, candidate review tasks, rule_version.candidate_id, processed_event
  versions/20261006_0011_candidate_version_keys.py   # composite keys tying a candidate's draft to its candidate and its task
tests/
  unit/            # domain, use cases and API on the memory store; test_models_vocabulary.py: model CHECKs against the kernel enums
  integration/     # testcontainers (pgvector image): migrations up, down and up; document tables and triggers; the Postgres unit of work and its reads; the search index; the publish guard, the outbox and the sweep; the changes feed read by a plain role; review tasks with their checks, index and guard; rule candidates, their tasks and the consumer's transaction
  contract/        # test_openapi.py: the served schema equals the committed spec; test_events.py: the rule events and rule.rejected match their schemas; test_golden_case_shape.py: an exported case equals packages/contracts/golden/extraction-case.example.yaml
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=rulebook     # alembic upgrade head in schema rulebook
make run SERVICE=rulebook         # http://localhost:8003/health, /ready, /v1/rulebook/ping, /v1/rulebook/documents/{id}
make relay SERVICE=rulebook       # relays the rule events in outbox_event to Kafka
make worker SERVICE=rulebook      # the sweep (CW_RULEBOOK_PUBLISH_ENABLED) and the candidate intake (CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED, with Kafka)
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
# entity_review, extraction_run, outbox_event, processed_event, relation_candidate, review_task,
# rule, rule_candidate, rule_relation, rule_version, rule_version_decision
```

Roll back with `CW_DATABASE_URL=... CW_DB_SCHEMA=rulebook uv run --package compliancewatch-rulebook alembic -c services/rulebook/alembic.ini downgrade base`
(the URL `make migrate` builds, with `?options=-csearch_path%3Drulebook%2Cpublic`).

Package `rulebook`, dev port 8003, Postgres schema `rulebook`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

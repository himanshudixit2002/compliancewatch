# ADR-018: The pipeline hands regulatory records to the rulebook over its HTTP API

- **Status:** Proposed
- **Date:** 2026-09-28
- **Deciders:** Regulatory Intelligence, AI Platform

## Context

The rulebook owns regulator documents, their clauses and the knowledge tables (Architecture
Reference, sections 4.1 and 6.2; ADR-017). The pipeline fetches and parses the documents, and
under ADR-017 it also finds the entities each clause mentions and proposes relations between
rules. Services never import each other and never share tables, so the parsed records have to
cross a service boundary.

The architecture describes that boundary as events: `document.parsed` and
`rule.candidate.created`, written to the pipeline's outbox and consumed by the rulebook
(section 4.2, ADR-005). None of that path exists for the pipeline yet. The pipeline has no
database, so no outbox table; the rulebook has no consumer; `document.parsed.v1` says that clause
text is read from a store that does not exist, since the raw file store is local and the clause
text is not in the event. Building the store, the outbox and the consumer first would delay the
knowledge work by a whole package, while the records are small (a notification is a few kilobytes
of clause text) and every write is keyed by ids both sides derive the same way.

## Decision

For now the pipeline writes to the rulebook through a small HTTP API, called from Temporal
activities:

- `PUT /v1/rulebook/documents/{document_id}` stores a parsed document and its clauses. The id is
  the first half of the document's SHA-256 digest (`domain_kernel.documents.document_id_for`),
  and each clause's id is derived from the document id and its ref (`clause_id_for`). The call is
  idempotent: the same parse again returns what is stored. A different parse of stored bytes is a
  409 and is never applied, because documents and clauses are append-only.
- Calls of the same kind store entity mentions, relation candidates and clause embeddings.
- The pipeline's writes need the shared secret `CW_RULEBOOK_WRITE_TOKEN` in the
  `x-cw-write-token` header, and a rulebook without that token refuses them (fail closed). Reads
  need no token.
- The analyst's actions on the same API (entity review decisions, relation approvals and
  rejections, citations, the rule version lifecycle and the transition sweep) need a second
  shared secret, `CW_RULEBOOK_REVIEW_TOKEN` in `x-cw-review-token`, and fail closed the same
  way. The pipeline keeps the write token and never gets the review token, and the write token
  does not open the analyst's routes, so a leaked pipeline secret cannot approve or publish a
  rule. The review token is a secret, not an identity: the `actor_id` and `decided_by` in those
  requests are still asserted by the caller until the identity service exists and issues them
  (ADR-014).
- The pipeline side sits behind `CW_PIPELINE_KNOWLEDGE_ENABLED`, default off, and behind
  `workflow.patched` in the ingest workflow, so recorded workflow histories replay unchanged. A
  failed registration is reported in the ingest result (`registered=False`,
  `registration_error`) and does not fail the ingest.
- The pipeline checks that the rulebook answered with the clause ids the kernel derives, which
  catches a version skew between the two deployments. Deploy the rulebook first.

The events stay the target. When the pipeline gets a database and an outbox, the registration
becomes `document.parsed` with the rulebook as a consumer; the ids, the idempotence rule and the
append-only rule carry over unchanged, and the HTTP write routes are retired.

## Alternatives considered

Events now. Correct in the long run, but it needs a pipeline database, an outbox migration, a
rulebook consumer with a dead-letter topic and a clause store the event can point at, all before
the first mention is aligned. The HTTP path gives the same guarantees for this volume.

A shared database schema. The pipeline could write the rulebook's tables directly. That breaks
table ownership (guide section 7) and the import-linter contract in spirit: two services would
own one schema's invariants.

## Consequences

- One synchronous dependency from the pipeline worker to the rulebook. A rulebook outage makes
  the registration activity retry with backoff; the rest of the ingest workflow is unaffected.
- Stored clauses are never replaced: mention spans and citations point into their text. A
  parser change that alters the text of a stored document makes its re-registration a 409.
  Whether stored documents are then kept as parsed, or get a second clause set under the new
  parser version (which would put the parser version into the clause id), is still to be
  decided, before the first parser change that alters clause text.
- The rulebook's write and analyst routes are reachable on its public Fly app, protected only by
  the two shared tokens until identity issues service tokens and user identities (ADR-014). Both
  must be long, different from each other and rotated with the other secrets; until then an
  approval records whichever approver id the caller sends.
- No `document.parsed` event is emitted yet; nothing consumes it today.
- Revisit when the pipeline gets its own tables, or when the write volume makes a synchronous
  call the bottleneck.

## Addendum 2026-09-29: service tokens and analyst roles replace the shared tokens

Identity now issues access tokens (ADR-014's addendum), and the rulebook reads them by
`CW_AUTH_MODE`. Its writes fall into two kinds:

- **Pipeline writes** (documents, mentions, relation candidates, clause embeddings) take the
  write token or a service token with the `rulebook:write` scope. The pipeline's worker and
  `pipeline-embed` send the service token once `CW_SERVICE_CLIENT_SECRET` is set, and the write
  token while it is configured.
- **Analyst actions** take the review token or a signed-in user with the route's roles: entity
  review decisions, relation approvals and rejections and the sweep take `analyst`, `reviewer` or
  `admin`; citations and submit take `analyst` or `rulebook:write`; return takes `analyst`,
  `reviewer` or `rulebook:write`; approve, publish and withdraw take `reviewer`. The rulebook
  README has the table.

The shared tokens open routes only in `header` and `dual` mode; in `token` mode, which production
requires, only an access token does. When a token names a user, the rulebook records that user
as `decided_by` or `actor_id` and ignores the body's value, so the two approvals of a high-impact
version come from two people rather than from whatever ids the caller sent. A service, which is
no person, still names the actor in the body. Regulatory sessions carry a second factor, which
identity enforces when it issues them. The consequence above about approver ids asserted by the
caller therefore holds only while an environment runs `header` mode, or `dual` mode without a
token.

## Addendum 2026-10-06: the parser version, and the first parse is kept

The pipeline now parses through a chain of parsers (the PDF's text layer `pdf@1`, a table-aware
`pdf-tables@1`, `html@1`, a table-aware `html-tables@1`, and `manual@1` for an analyst's
transcript of a document no parser reads), so the same stored bytes can be parsed by more than
one parser over time. This is the first parser change that alters clause text, and it settles
the decision left open above: **stored documents are kept as parsed**.

- The pipeline records the parser of each document's parse on its own row
  (`raw_document.parser_version`, `name@version`) and sends it with every registration
  (`parser_version`, as it always did). It parses a stored document again with the parser it
  recorded, as long as the code has that parser, so a re-registration sends the same clauses.
- The rulebook keeps the first parse it stores. A registration of a stored document by another
  parser version (a newer parser, a version bump that left the old one behind, or an analyst's
  transcript of a document parsed before) is answered `200` with the stored clauses' ids, the
  stored `parser_version` in the new response field `parser_version`, and `parser_version` among
  `metadata_differs`. Nothing is written and nothing is refused, so re-registering a document a
  newer parser parsed never gets a 409. The pipeline checks that the kept clauses carry the ids
  the kernel derives for their refs, which still catches a version skew.
- A different parse by the **same** parser version is still a 409: that parser changed what it
  gives for the same bytes without a new version, which is a bug. Bump a parser's version with
  any change that can alter its clause text or refs for the same bytes.
- The parser version stays out of the clause id. Clause refs stay `<language>.p<n>` for every
  parser, so the rulebook's ref pattern and its clause ids are unchanged, and mention spans and
  citations keep pointing at the clauses they were made on.

This changes the rulebook's semantics: before, any different parse of stored bytes was a 409.
A better parse of a document stored before is therefore not applied by itself; storing a second
clause set under a new parser version, as a new version of the document, is a decision for when
an analyst needs one. `document.parsed` 1.1.0 now carries each parse with its parser, but the
registration stays on HTTP, since the event carries no clause text.

## Addendum 2026-10-06: classification, extraction in the workflow, and the candidate it publishes

The ingest now classifies every parsed document and extracts a rule candidate from the ones a
rule can come from. Both steps sit behind workflow patches (`pipeline-classify-v1`,
`pipeline-extraction-v1`), so histories recorded before them replay unchanged; the extraction
also sits behind the flag `pipeline.extraction` (`CW_PIPELINE_EXTRACTION_ENABLED`, default off,
owner regulatory-intelligence).

**Classification comes before registration.** A rule-based classifier (the detector, no model)
reads the opening of each parsed document for the type it names, compares it with the type its
source publishes, and says how sure it is: `certain`, `default` (the text names no type, the
source's is taken) or `conflict`. It also says whether the document is a regulatory one at all.
The classification is recorded in the pipeline's store with the document's status and a
`document.classified` event, in one transaction. A conflict opens a `triage` task in the same
transaction and the document is not registered until a person decides; an irrelevant document is
never registered; a press release or a statute is registered for reference and nothing is
extracted from it. The rulebook keeps the type of a document's first registration, so registering
before the type is settled would freeze a wrong one there; the registration now sends the type
the classification gave. A person's triage is stored on the task's resolution and becomes the
document's classification; the stored raw document's own `doc_type` (the uploader's) never
changes, and the triage's resolution starts an ingest of the stored document that registers it as
the decided type.

**The extraction reads what the rulebook keeps.** Once a notification, circular or act amendment
is classified and registered, the ingest starts a child workflow, `pipeline.extract_rules`, and
leaves it running (`ParentClosePolicy.ABANDON`), so neither the ingest nor the crawl above it
waits for a model or a budget. The child reads the document back from the rulebook, as
`ExtractMentions` does, so every citation it makes points at a clause the rulebook stores (the
first parse, per the addendum above). It therefore needs `pipeline.knowledge`, and check-config
refuses the extraction without it outside local and test.

**Two activities, keyed by document and prompt version.** `pipeline.extract_rules` asks the
llm-gateway with the registered prompt `extraction.rule_candidate@1` (unchanged, with its eval
cases) and writes nothing; `pipeline.store_extraction` stores the answer (`rule_extraction`, one
row per document and prompt version, kept as written by a trigger) with its
`rule.candidate.created`, through the outbox, in one transaction. The answer crosses the workflow
as data, so a failed write never asks the model again, and an extraction stored before is
returned without a model call. The candidate's id is derived from the document and the prompt
version, so the same extraction always names the same candidate.

**Retries.** An answer that is not a candidate (not JSON, not the schema's shape, or outside the
schema's limits that the parser does not check) is asked for once more, at a small temperature:
the gateway caches deterministic calls, so asking the same way would return the same answer. Two
such answers are stored as `unparseable`, with no candidate and the reason, for an analyst to
draft by hand. A used-up budget is the gateway's problem type `llm-budget-exceeded` (a 429 with
`Retry-After` until the budget resets): the activity hands it to the workflow without retrying,
and the workflow sleeps on a durable timer, between 15 minutes and 6 hours, and asks again, at
most 160 times (some 40 days). This replaces the gateway's deferral queue, which is dropped from
the plan. Any other failure fails the child, and the document stays `classified` until a
re-ingest of it starts the extraction again.

**The candidate is a contract.** `rule.candidate.created` 1.1.0 adds, as optional fields: the
outcome, the candidate in the extraction schema's shape (the schema file keeps the extractor's
`CANDIDATE_SCHEMA` under `$defs`, and a contract test keeps the two equal), the validators'
issues, a suggested rule key (`<form>_<cadence>`, as the seed calendar names rules; a suggestion
for the analyst, never a lookup in the rulebook), the ids of the cited clauses as the kernel
derives them, the type it was extracted as and its source. `regulator` and `confidence` were
already required. This is the first record the pipeline hands the rulebook as an event rather
than over HTTP; the rulebook's candidate intake, which is not built yet, consumes it, and sets a
review's priority from `needs_review`, `confidence` and `outcome` and its regulator from
`regulator`. Registration stays on HTTP.

Consequences:

- A prompt version whose output schema differs changes the event: the candidate block is a
  closed schema (its objects forbid other fields), so a new field in it is a new event major
  version, not a minor one.
- The detector's reading of the opening is now consequential: a false conflict holds a document
  out of the rulebook until a person triages it. The type a person gave (an upload's, a triage's)
  is taken as it is, a statute source's documents are statutes whatever they quote, and "the
  recommendations of the Council", which nearly every notification says, no longer reads as a
  press release.
- Classification runs whatever the flag says: with the extraction off, a classified notification
  waits as `classified`. Turning the flag on later does not extract that backlog by itself: a
  re-ingest of a document (an upload of the same file, say) finds its classification and
  extracts it, and a sweep of the documents waiting as `classified` is not built yet. The
  backfill command never extracts.

## Addendum 2026-10-06: the rulebook's candidate intake, drafting and rejection

The rulebook now consumes `rule.candidate.created` and puts each candidate in front of an
analyst. The intake runs in the rulebook worker, in consumer group `rulebook.rule-candidates`,
behind the flag `rulebook.candidate_intake` (`CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED`, default off,
owner regulatory-intelligence); off, no group reads the topic, which keeps the candidates a month,
and the group reads them from the start once it is on.

**One candidate, one task, in one transaction with the inbox.** Each event is checked against
its contract and stored once per `candidate_id` in `rule_candidate` (the scores in columns, the
candidate, its issues, the cited clause ids and the source in `payload`), with one review task of
kind `candidate`, in the transaction that records the event in `processed_event`. A candidate
whose document the rulebook does not store fails and is dead-lettered after its retries; the
pipeline registers a document before it extracts from it, so a replay takes it in. The
regulator is kept in lower case, as the rulebook's rules name it. The task's priority is the
policy of the queue: 100 when the candidate looks high impact (it extends a deadline or withdraws
something, its `applies_to` is empty, or it names amounts), 80 when there is no candidate to draft
from, 50 when the extraction asked for review or a validator found an issue, 10 otherwise. The
pipeline's suggested rule key is kept as a suggestion: a key no rule has gives way to the one rule
key the document's relation candidates name (those an analyst rejected left out), and the task
says whether a rule has the key.

**Drafting is an analyst's step, never the intake's.** No transition discards a draft, so a wrong
draft made automatically would linger. The analyst who claimed the task drafts a version from the
candidate (`POST /v1/rulebook/review/tasks/{task_id}/draft`): into an existing rule as its next
version, or as the first version of a new rule with an unused key, its level and the candidate's
regulator. The version names its candidate (`rule_version.candidate_id`) and starts high impact
when the candidate suggests it; a reviewer may raise it, never lower it. Its content is the
candidate's, mapped into the kernel's forms, with the analyst's edits, checked as the seed calendar
is checked; a condition the kernel refuses leaves the specification out rather than widen the
rule. The citations are verified against the clauses the rulebook stores. The relation candidates
the analyst picks from the document are approved onto the draft in the same transaction, so an
`extends_deadline` the knowledge child staged reaches the publication, whose rule.deadline_changed
the obligation worker turns into rescheduled obligations. What the analyst changed from the
candidate is recorded as an `edited` decision; a candidate taken as it was records none, and the
review stats count it as approved without edits, the acceptance this ADR's extraction is measured
by. The seed command leaves a candidate's draft alone and updates only its own draft, the rule's
latest version not drafted from a candidate, so a candidate's draft beside it never freezes the
rule; it locks the rule's row as drafting does, so the two never take one version number. No seed
task is opened for a candidate's draft.

**Rejection is a decision with a reason and an event.** A candidate task's rejection names why
(`not_a_rule`, `wrong_extraction`, `duplicate`, `out_of_scope`, `unparseable`), closes the
candidate before or after drafting, and writes `rule.rejected` 1.0.0 through the rulebook's outbox
in the decision's transaction. A draft made from a rejected candidate stays a draft, since no
transition discards one, but it is closed:

- it never moves on: citing it, approving a relation from it, submitting, approving and
  publishing it are refused with 409 `rulebook-rule-version-closed`, on the review task routes and
  the generic ones alike;
- it is never its rule's latest version: the seed command and `GET /v1/rulebook/rules` skip it,
  so its model-written title never reaches the pipeline's relation prompt, and the rule's next
  version is numbered past it;
- the relation candidates approved onto it are open again, in the rejection's transaction, with a
  note saying why, and their `rule_relation` rows are deleted. Approval takes only open
  candidates and staging a proposal again changes nothing, so without this an `extends_deadline`
  approved onto a rejected draft could never reach a corrected one, and the obligations it
  reschedules never would be.

A version the publish routes published before the rejection stands, with its relations.

**The database keeps a candidate's draft its own.** Migration 0011 adds composite foreign keys
from `review_task (rule_version_id, candidate_id)` and from `rule_candidate (rule_version_id, id)`
to `rule_version (id, candidate_id)`, so a candidate task, and its candidate, name only the
version drafted from that candidate; a seed task and a task not drafted yet are not checked.
0010's downgrade refuses while a rule candidate or a candidate task is stored, before it changes
anything.

**The review task routes change shape.** A candidate task has no rule version until it is
drafted, so `rule_version_id` and the version fields of the queue, and the version of a task's
detail and of a decision, are null until then, and every task's `kind` admits `candidate`. One
client reads these routes: the local product's check (`cw-product check`, `review_queue`,
`claim_one` and `read_task` in `tools/demo/src/cw_demo/product/check.py`) lists the queue, claims
a seed task and reads it. It changes in the same pull request to accept a null `version_status`
and to claim seed tasks only, so the shape changes in place, recorded in
`packages/contracts/openapi/BREAKING.md`. The review workbench (W10) is not built and is built on
the new shape.

Consequences:

- `make product` leaves the intake off, so the product never writes candidates into the database
  it shares; the intake is proved by the rulebook's tests on Postgres and by
  `tools/demo/tests/unit/test_candidate_flow.py` on the one deployable's memory stores.
- A version drafted from an extension notification is a rule version like any other: its own
  specification and template fan out when it is published. Whether such a version should apply
  to nobody (a specification such as `any_of: []`) and only move the deadline is for Regulatory
  Intelligence to decide; the journey's draft does so only to show the plumbing.

## Addendum 2026-10-06: a person's type on a retry, the backlog sweep and the backfill

The pipeline gets its operations: every source's crawl runs and documents, a person's retry of a
stored document, the outbox's dead rows and their requeue (`/v1/pipeline/runs`,
`/v1/pipeline/documents`, `/v1/pipeline/documents/{id}/retry`, `/v1/pipeline/outbox/dead`,
`/v1/pipeline/outbox/{event_id}/requeue`), reads for a regulatory role and writes for an admin
with a reason, audited. Two of them change how a document is classified.

**A type given on a retry is a person's classification.** An admin may give a `doc_type` on a
retry, from any stage. It becomes the document's classification as a triage's decision does:
relevant, of that type, `certain`, classifier `retry`, the admin in `decided_by`, recorded with
the document's status and a `document.classified`, and audited as `pipeline.document.retry`, in
the retry's transaction with the document's row locked; the stored raw document's own type (the
uploader's) never changes. It beats the detector, as the triage's decision does, and it is the
way back for a document the detector set aside as irrelevant, or whose triage was dismissed,
which before had none: a typed re-upload of the same bytes is a duplicate and changes nothing,
and an irrelevant document has no task to resolve. While a triage task holds the document the
retry is refused, so a decision is taken in one place at a time. Migration 0005 lets a
classification decided by a person be a `retry`'s as well as a `triage`'s.

**A retry from the classify stage reads the document again.** Behind the workflow patch
`pipeline-reclassify-v1`, the ingest of a retry from `classify` given no type asks the classify
step for a fresh reading: today's detector reads the document again, and a reading that differs
replaces the detector's earlier one, with its status, a `document.classified` and, for a
conflict, a triage task. A person's decision (a triage's, a retry's type) is never read again.
Every other ingest keeps a classification it finds, as before.

**The backlog and the backfill.** The consequence above that a sweep of the documents waiting as
`classified` is not built yet no longer holds: `pipeline-extract-backlog` starts
`pipeline.extract_backlog`, which runs each waiting document's extraction as a child under the id
the ingest's own extraction would have, so a document is extracted once whichever starts it, and
the command refuses while `pipeline.extraction` is off. The backfill now goes through the crawl
workflow from a plan (`pipeline-backfill --plan ... --workflow`, a crawl run with the trigger
`backfill` behind the patch `pipeline-backfill-v1`), so its documents are classified and, with
the flag on, extracted like any crawl's; the command that fetched into a local raw store and
extracted nothing stays behind `--legacy` for recording fixtures.

Consequences:

- A person can now bring back a document the detector set aside, which before nothing could: a
  re-upload of the same bytes is a duplicate, and the crawl never fetches a stored URL again.
  Their type is audited with the reason and stands against every later ingest; to change it,
  another retry with another type.
- The patches keep the histories recorded before them replaying: an ingest without the reclassify
  marker keeps the classification it finds, and a crawl that names no window records no marker.

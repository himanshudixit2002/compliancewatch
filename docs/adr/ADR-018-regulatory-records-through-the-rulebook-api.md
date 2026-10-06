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

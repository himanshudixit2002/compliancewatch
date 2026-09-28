# ADR-018: The pipeline hands regulatory records to the rulebook over its HTTP API

- **Status:** Proposed
- **Date:** 2026-09-28
- **Deciders:** Regulatory Intelligence, AI Platform

## Context

The rulebook owns regulator documents, their clauses and the knowledge tables (Architecture
Reference, sections 4.1 and 6.2; ADR-017). The pipeline fetches and parses the documents, and in
phase 2 of ADR-017 it also finds the entities each clause mentions and proposes relations between
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
- Phase 2b adds the same kind of calls for entity mentions and relation candidates.
- Writes need the shared secret `CW_RULEBOOK_WRITE_TOKEN` in the `x-cw-write-token` header, and
  a rulebook without a token refuses every write (fail closed). Reads need no token.
- The pipeline side sits behind `CW_PIPELINE_KNOWLEDGE_ENABLED`, default off, and behind
  `workflow.patched` in the ingest workflow, so recorded workflow histories replay unchanged.
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
- The rulebook's write routes are reachable on its public Fly app, protected only by the shared
  token until identity issues service tokens (ADR-014). The token must be long and rotated with
  the other secrets.
- No `document.parsed` event is emitted yet; nothing consumes it today.
- Revisit when the pipeline gets its own tables, or when the write volume makes a synchronous
  call the bottleneck.

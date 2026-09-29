# ADR-003: PostgreSQL with pgvector as system of record and vector store until Phase 3

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Platform and Infrastructure, Regulatory Intelligence, AI Platform

## Context

The data is transactional records (tenants, profiles, rules, decisions, obligations) that need
row-level security per tenant, plus clause embeddings for hybrid retrieval and keyword search
over clause text. Retrieval must apply metadata filters first (regulator, published status,
effective dates as of a date) and only then rank by similarity, and those filter fields are the
same columns the rulebook service keeps as transactional data. Year one is about 10,000
businesses, 20 sources and 50 documents a day; year three is planned at 500,000 businesses,
200 sources and 2,000 documents a day, which is on the order of a million clauses. A separate
vector database from day one was considered: it would duplicate the filter columns, need dual
writes, and be one more system for a small team to run before the volume justifies it.

## Decision

PostgreSQL 16 on Aurora in ap-south-1 is the system of record, one schema per service, row-level
security on every tenant table, JSONB only for the ontology-governed attributes and predicates.
pgvector with an HNSW index stores clause embeddings in the clause row itself, and Postgres
full-text search provides the keyword leg of retrieval. Redis holds caches, sessions and rate
limits. The exit criteria are fixed now rather than argued later: move vectors to Qdrant when
they exceed about 50 million or p95 vector search exceeds 150 ms; add OpenSearch (ADR-010) when
keyword search must span 200 or more sources and more than one language; split the high-write
schemas (decisions, notifications) to their own clusters past about 5,000 writes per second.

## Consequences

- One engine to run, back up (point-in-time recovery, RPO 15 minutes) and secure; a clause and
  its embedding are one row, so filters and vectors can never disagree.
- Embeddings carry the model name and version; a model change is a new column and a background
  re-embed, never an overwrite.
- HNSW index build time and memory need watching as clauses grow, and Postgres full-text ranking
  is weaker than a dedicated BM25 engine. Both are acceptable at a million English clauses.
- pgvector will fall behind a dedicated engine at some size. The numbers above are the trigger,
  read from database metrics and the eval dashboard, not from a feeling.
- Revisit at any of the three exit criteria, or if residency or Aurora cost changes the picture.

## Addendum 2026-09-29: embeddings in a side table

The embeddings do not sit in the clause row. `clause` is append-only (a trigger refuses every
update, so a clause never changes after it is registered), and a vector column on it could never
be filled after the fact or replaced. Rulebook migration 0006 puts them in a side table instead:
`clause_embedding(clause_id, model, embedding vector(512), created_at)`, keyed by
(`clause_id`, `model`), with an HNSW index for cosine distance and a trigger that refuses updates.
The length is the kernel's `EMBEDDING_DIMS`; the model is the name the gateway served the vector
under.

- A model change is a re-embed into new rows under the new model's name, not a new column and
  never an overwrite: the pipeline's `pipeline-embed --model <new>` fills them before the
  gateway's retrieval route switches, and the old model's rows can be deleted once nothing
  searches them. A search always compares vectors of one model.
- A clause and its embedding are two rows rather than one, but in the same schema and joined by
  a foreign key, so filters and vectors still cannot disagree: the search applies its filters
  through the join to `clause` and `document`.
- The keyword leg is a stored generated column on `clause` (`search_vector`,
  `to_tsvector('english', text)`, GIN index); adding it rewrote the table rather than updating
  rows, so the append-only trigger was never involved.
- pgvector is created in the `public` schema, which every service keeps on its search path.

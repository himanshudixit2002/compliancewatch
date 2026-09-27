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

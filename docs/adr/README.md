# Architecture decision records

Numbered ADRs, one file each. Titles, status and the one-line rationale come from the Project Foundation guide, section 21 (decision log); the full text of each ADR is still to be written. A new ADR is required for every architectural decision and for every breaking contract change (guide sections 4 and 14).

- [ADR-001: Monorepo with one directory per service and a shared contracts package](ADR-001-monorepo-one-directory-per-service.md) (Accepted)
- [ADR-002: Python and FastAPI for services; Next.js and TypeScript for apps](ADR-002-python-fastapi-services-nextjs-apps.md) (Accepted)
- [ADR-003: PostgreSQL with pgvector as system of record and vector store until Phase 3](ADR-003-postgres-pgvector-until-phase-3.md) (Accepted)
- [ADR-004: Temporal for pipeline and fan-out orchestration](ADR-004-temporal-for-pipeline-and-fan-out.md) (Accepted)
- [ADR-005: Kafka with a transactional outbox for all domain events](ADR-005-kafka-with-transactional-outbox.md) (Accepted)
- [ADR-006: No rule is published without human approval; two-person rule for high-impact](ADR-006-human-approval-before-publish.md) (Accepted)
- [ADR-007: Deterministic predicates first; LLM judgement only for free-text conditions, with confidence and review routing](ADR-007-deterministic-predicates-first.md) (Accepted)
- [ADR-008: Own LLM gateway; no LangChain or LlamaIndex in production code](ADR-008-own-llm-gateway-no-langchain.md) (Accepted)
- [ADR-009: Keycloak self-hosted for identity](ADR-009-keycloak-self-hosted.md) (Proposed)
- [ADR-010: OpenSearch added in Phase 3 for keyword search at scale](ADR-010-opensearch-in-phase-3.md) (Proposed)
- [ADR-011: India-first with GST as the launch regulator and FSSAI second](ADR-011-india-first-gst-then-fssai.md) (Proposed)

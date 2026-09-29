# Architecture decision records

Numbered ADRs, one file each. Titles and status for ADR-001 to ADR-011 come from the Project
Foundation guide, section 21 (decision log); ADR-012 and ADR-013 come from the Architecture
Reference v1.0, section 9.2 (decision log). ADR-001 to ADR-008 and ADR-012 to ADR-019 have their
full text; ADR-009 to ADR-011 are stubs that keep the decision log's one-line rationale until
they are written. ADR-014 (identity for the MVP), ADR-015 (recurring obligations and deadline
changes) and ADR-016 (business hierarchy) record decisions of 2026-09-28; ADR-017 the KAG-style
reasoning decision of the same day, and ADR-018 how the pipeline hands records to the rulebook.
ADR-019 (2026-09-29) records how the web app reaches the services: through its server layer
only, with an encrypted stateless session.
Dated addenda of 2026-09-29 record what the question-answering work built against four of them:
ADR-003 (embeddings in a side table), ADR-008 (embeddings through the gateway), ADR-012 and
ADR-017 (what shipped, the first evaluation numbers and what each needs to be Accepted). A new
ADR is required for every architectural decision and for every breaking contract change (guide
sections 4 and 14).

- [ADR-001: Monorepo with one directory per service and a shared contracts package](ADR-001-monorepo-one-directory-per-service.md) (Accepted)
- [ADR-002: Python and FastAPI for services; Next.js and TypeScript for apps](ADR-002-python-fastapi-services-nextjs-apps.md) (Accepted)
- [ADR-003: PostgreSQL with pgvector as system of record and vector store until Phase 3](ADR-003-postgres-pgvector-until-phase-3.md) (Accepted)
- [ADR-004: Temporal for pipeline and fan-out orchestration](ADR-004-temporal-for-pipeline-and-fan-out.md) (Accepted)
- [ADR-005: Kafka with a transactional outbox for all domain events](ADR-005-kafka-with-transactional-outbox.md) (Accepted)
- [ADR-006: No rule is published without human approval; two-person rule for high-impact](ADR-006-human-approval-before-publish.md) (Accepted)
- [ADR-007: Deterministic predicates first; LLM judgement only for free-text conditions, with confidence and review routing](ADR-007-deterministic-predicates-first.md) (Accepted)
- [ADR-008: Own LLM gateway; no LangChain or LlamaIndex in production code](ADR-008-own-llm-gateway-no-langchain.md) (Accepted)
- [ADR-009: Keycloak self-hosted for identity](ADR-009-keycloak-self-hosted.md) (Proposed, stub)
- [ADR-010: OpenSearch added in Phase 3 for keyword search at scale](ADR-010-opensearch-in-phase-3.md) (Proposed, stub)
- [ADR-011: India-first with GST as the launch regulator and FSSAI second](ADR-011-india-first-gst-then-fssai.md) (Proposed, stub)
- [ADR-012: Layered retrieval: structured, hybrid RAG, SQL entity joins, agentic fallback](ADR-012-layered-retrieval.md) (Proposed)
- [ADR-013: Managed MVP deployment profile before the Kubernetes profile](ADR-013-managed-mvp-deployment-profile.md) (Proposed)
- [ADR-014: Supabase Auth as the identity provider of the MVP profile; Keycloak stays the option for the Kubernetes profile](ADR-014-supabase-auth-for-the-mvp.md) (Proposed)
- [ADR-015: Recurring obligations are materialised per period; deadline changes reschedule open obligations](ADR-015-recurring-obligations-and-deadline-changes.md) (Proposed)
- [ADR-016: Business hierarchy: legal entity (PAN), registration (GSTIN), location](ADR-016-business-hierarchy-pan-gstin-location.md) (Proposed)
- [ADR-017: KAG-style reasoning over the rulebook in PostgreSQL](ADR-017-kag-style-reasoning.md) (Proposed)
- [ADR-018: The pipeline hands regulatory records to the rulebook over its HTTP API](ADR-018-regulatory-records-through-the-rulebook-api.md) (Proposed)
- [ADR-019: The web app reaches the services only through its server layer, with an encrypted stateless session](ADR-019-web-server-layer-and-stateless-session.md) (Proposed)

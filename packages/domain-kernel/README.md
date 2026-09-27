# domain-kernel package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 11, 13 and 20.

- **Owns:** Shared value objects, protocols (SourceAdapter, DocumentParser, RuleExtractor, PredicateEvaluator, NotificationChannel, LLMProvider, VectorStore), Ontology loader, error types
- **Owning team:** Platform and Infrastructure (custodian; Phase 0 golden-path deliverable) (guide section 14)
- **Consumes:** packages/ontology
- **Emits / publishes:** n/a (library)

## Layout

Installable stub (`src/domain_kernel`, package `domain-kernel`); the section 11 protocols and value objects arrive in the domain-kernel slice.

## How to run

`uv run pytest packages/domain-kernel` from the repo root.

# domain-kernel package

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 11, 13 and 20.

- **Owns:** Shared value objects, protocols (SourceAdapter, DocumentParser, RuleExtractor, PredicateEvaluator, NotificationChannel, LLMProvider, VectorStore), Ontology loader, error types
- **Owning team:** Platform and Infrastructure (custodian; Phase 0 golden-path deliverable) (guide section 14)
- **Consumes:** packages/ontology
- **Emits / publishes:** n/a (library)

## Layout

Flat for now; Python package layout to be added with the uv workspace in Phase 0.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

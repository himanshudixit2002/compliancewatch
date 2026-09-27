# golden sets

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 8, 14 and 19.

- **Owns:** Golden sets as versioned data files, reviewed like code: extraction (starts at 200 documents), qa (starts at 500 questions), applicability (target 2,000 labelled decisions by Phase 3)
- **Owning team:** Regulatory Analysts (an analyst approves every addition); AI Platform owns the tooling (guide section 14)
- **Consumes:** Review edits, "not covered" answers and user thumbs-down after analyst triage
- **Emits / publishes:** Versioned golden data consumed by evals/harness

## Layout

```
extraction/     # document -> expected RuleCandidate
qa/             # question -> expected grounded answer and citations (or not_covered)
applicability/  # (profile, rule version) -> expected decision
```

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

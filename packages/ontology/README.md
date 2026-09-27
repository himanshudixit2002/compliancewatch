# ontology package

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 6, 13 and 14.

- **Owns:** Attribute definitions as YAML, versioned, with a validator (registration_type, turnover_band, state_codes, business_category, employee_count, ...)
- **Owning team:** Core Product, co-approved by Regulatory Intelligence; content proposed by the Regulatory Analysts (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Ontology versions on a monthly release train; the engine and the profile service upgrade together

## Layout

Flat for now; YAML attribute files and the validator arrive with Ontology v0 (about 15 GST attributes) in Phase 0.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

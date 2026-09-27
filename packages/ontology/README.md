# ontology package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 6, 13 and 14.

- **Owns:** Attribute definitions as YAML, versioned, with a validator (registration_type, turnover_band, state_codes, business_category, employee_count, ...)
- **Owning team:** Core Product, co-approved by Regulatory Intelligence; content proposed by the Regulatory Analysts (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Ontology versions on a monthly release train; the engine and the profile service upgrade together

## Layout

Installable stub (`src/ontology`, package `ontology`); YAML attribute files and the validator arrive with Ontology v0 (about 15 GST attributes).

## How to run

`uv run pytest packages/ontology` from the repo root.

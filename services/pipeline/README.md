# pipeline service

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 5, 7, 8, 11 and 14.

- **Owns:** The regulatory intelligence pipeline as Temporal workers: source-crawler (source registry, fetch schedule, raw document store), change-detector (document classification, links to prior documents), doc-parser (clause-level structured text, OCR fallback), rule-extractor (schema-validated RuleCandidates with verified citations), review-service (ReviewTasks, decisions, edit diffs, two-person rule)
- **Owning team:** Regulatory Intelligence; `prompts/` is owned by AI Platform and reviewed by a Regulatory Analyst (guide section 14)
- **Consumes:** Cron per source; admin API; document.discovered; document.classified; document.parsed; rule.candidate.created; workbench UI; LLM gateway API
- **Emits / publishes:** document.discovered, document.classified, document.parsed, rule.candidate.created, rule.published, rule.rejected

## Layout

```
src/pipeline/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters
  main.py          # composition root (to be added by the service template)
migrations/        # alembic
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
pyproject.toml, Dockerfile   # to be added by the service template
```
Doc-literal subdirectories at the service root (guide section 13; the CI eval trigger in section 17 watches `services/pipeline/prompts`):

```
adapters/    # SourceAdapter implementations, one file per regulator source (cbic_notifications, cbic_circulars, fssai_orders)
parsers/     # DocumentParser implementations (PDF, HTML, OCR)
prompts/     # Versioned prompt files, each with a version, an owner and at least one eval case
workflows/   # Temporal workflows and activities for the five stages
```

`adapters/`, `parsers/` and `workflows/` may move under `src/pipeline/` when the service template lands, so that they are importable in the src layout.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.

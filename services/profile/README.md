# profile service

Part of the ComplianceWatch monorepo. **The business hierarchy, attribute values per node and financial year, snapshots, one-question onboarding and review tasks exist behind a first API; the GSTIN lookup adapter and the identity token are not built yet.**
Design reference: Project Foundation guide, sections 6, 7 and 14.

- **Owns:** BusinessProfiles and the Ontology attribute store; validates attributes against the Ontology; versions each change; GSTIN pre-fill. Python package: `profile_service` (the stdlib ships a `profile` module)
- **Owning team:** Core Product (guide section 14)
- **Consumes:** Onboarding UI; GSTIN lookup adapter; partner API
- **Emits / publishes:** profile.updated (through the outbox)

## What is here

The hierarchy of ADR-016: a legal entity keyed by PAN, registrations keyed by GSTIN under it,
locations under a registration. Every attribute of ontology 0.2.0 declares its level, so a
value is stored on the node of that level and inherited downward when a snapshot is built for
the applicability engine. A per-financial-year attribute (the turnover band) is stored once
per year and the snapshot picks the year asked for.

- `domain/model.py`: `ProfileNode` (`entity`, `registration`, `location` constructors that
  check the PAN inside the GSTIN and the parent's level), `AttributeRecord` with a state
  (`known`, `unsure`, `not_applicable`), `apply` (the ontology validates, the version bumps,
  one `profile.updated` per batch, a review request per `not_applicable` answer), `snapshot`
  (lineage merged, child values win), `next_question` (the first missing or unsure attribute
  of the node's level: one question at a time, never a form), `missing_for_year`.
- `application/registration.py`: entity by PAN, registration by GSTIN (its PAN finds or creates
  the entity), location under a registration; idempotent on the key.
- `application/attributes.py`: `SetAttributes` (event to the outbox; a `not_applicable` answer
  opens a `ReviewTask` and records a golden-case seed through the eval recorder), `NextQuestion`,
  `BuildSnapshot`, `ConfirmFinancialYear` (one `confirm_financial_year` task per entity and
  per-year attribute missing for the new year: the April task).
- `api/`: `POST /v1/profile/{entities,registrations,locations}`, `GET /v1/profile/nodes/{id}`,
  `PUT /v1/profile/nodes/{id}/attributes`, `GET .../snapshot?fy=2025-26`,
  `GET .../next-question?fy=`, `GET .../review-tasks`,
  `POST /v1/profile/financial-year-confirmations`. The tenant is the `x-tenant-id`
  header (required, 401 without it) until the identity service issues tokens (ADR-014). Errors
  are problem details; the spec is `packages/contracts/openapi/profile.v1.json`
  (`make openapi SERVICE=profile`, checked by a contract test).
- `infrastructure/`: `PostgresUnitOfWorkFactory` (one transaction per call, `app.tenant_id`
  set for the row-level security policies on all four tables, events through the outbox,
  eval cases through an optional JSON-lines recorder at `CW_PROFILE_EVAL_CASES_PATH`);
  `memory.py` is the in-memory twin (`CW_PROFILE_STORE=memory`, the tests and demos).
- `migrations/versions/20260928_0001_profile_hierarchy.py`: `profile_node`,
  `profile_attribute`, `profile_version` (history), `review_task`, each with tenant_id and a
  forced policy, plus the outbox and inbox tables.

Row-level security binds only non-superuser roles; see the obligation service README for the
dev-stack caveat. Settings: `CW_PROFILE_STORE` (`postgres` default, `memory`),
`CW_PROFILE_EVAL_CASES_PATH` (empty keeps the eval seed in the review task only).

## Financial year confirmation

On 1 April a new financial year starts, and per-year attributes (the turnover band) have no
value for it yet. `POST /v1/profile/financial-year-confirmations` (tenant header, optional body
`{"fy": "2026-27"}`) runs `ConfirmFinancialYear` for the tenant: one `confirm_financial_year`
review task per entity and per-year attribute missing for that year, answered 200 with
`{"fy", "opened": [task ids]}`. Without `fy` it takes the financial year of today's date in
India Standard Time. It is idempotent: a task still open for the same entity, attribute and
year is not opened again, so a second call opens nothing. The command
`profile-fy-confirm --tenant <uuid> [--tenant <uuid> ...] [--fy 2026-27]` does the same for
named tenants from a shell (`uv run --package compliancewatch-profile profile-fy-confirm ...`;
`CW_PROFILE_STORE` and `CW_DATABASE_URL` pick the store). Nothing calls either on a schedule
yet: the daily job that confirms every active tenant from 1 to 7 April arrives with identity's
worker, since under forced row-level security nothing here can list tenants.

## GSTIN lookup

`POST /v1/profile/registrations/{id}/prefill` asks the `GstinLookupProvider` for the
registration's GSTIN and stores what comes back as attribute values with source
`gstin_lookup` (registration type, GSTIN status, constitution, registered since). With no
provider (`CW_PROFILE_GSTIN_LOOKUP=manual`, the default) the person proceeds manually and a
`verify_registration` review task is opened once per registration; `static` serves a made-up
demo table. A real provider (GSTN through a GSP, or an aggregator) is an account the
maintainer opens; it plugs in behind the protocol in `domain/lookup.py`.

Whatever the lookup answers, the GSTIN's first two digits are its state code, so the entity's
`state_codes` gains that code, joined to the codes it already has, with source `derived`. A
code the ontology does not list (97, 99) is skipped. `business_category` is written from the
registry's nature of business only while the flag `profile.gstin_category_prefill` is on for
the tenant (off by default) and the activities map to exactly one category; the mapping is
reviewed by an analyst before the flag goes on.

## Layout

```
src/profile_service/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters
  main.py          # composition root: create_app(...) from py-common
  jobs.py          # profile-fy-confirm: the financial year confirmation for named tenants
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # provider-side contract tests for this service's API and events
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=profile
make run SERVICE=profile           # http://localhost:8002/health, /ready, /v1/profile/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/profile/Dockerfile -t compliancewatch-profile .
```

Package `profile_service`, dev port 8002, Postgres schema `profile`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

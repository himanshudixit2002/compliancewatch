# profile service

Part of the ComplianceWatch monorepo. **The business hierarchy, attribute values per node and financial year, snapshots, one-question onboarding and review tasks exist behind a first API, with the public business API and `GET /v1/ontology` on top; the GSTIN provider account does not exist yet, so the HTTP lookup stays off. The tenant comes from a verified access token or, while `CW_AUTH_MODE` is `header` (the default), from the `x-tenant-id` header.**
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
  `POST /v1/profile/financial-year-confirmations`. Every route but the ping acts for one
  tenant (see Authentication below; 401 `tenant-required` without one). Errors
  are problem details; the spec is `packages/contracts/openapi/profile.v1.json`
  (`make openapi SERVICE=profile`, checked by a contract test).
- `infrastructure/`: `PostgresUnitOfWorkFactory` (one transaction per call, `app.tenant_id`
  set for the row-level security policies on all four tables, events through the outbox,
  eval cases through an optional JSON-lines recorder at `CW_PROFILE_EVAL_CASES_PATH`);
  `memory.py` is the in-memory twin (`CW_PROFILE_STORE=memory`, the tests and demos).
- `migrations/versions/20260928_0001_profile_hierarchy.py`: `profile_node`,
  `profile_attribute`, `profile_version` (history), `review_task`, each with tenant_id and a
  forced policy, plus the outbox and inbox tables. `20260929_0003_business_api.py` adds
  `idempotency_key` (py-common's, with the forced tenant policy and the purge policy) and the
  index `ix_profile_node_tenant_level_name` the business list pages on.

Row-level security binds only non-superuser roles: `make run` and `make web-stack STORE=postgres`
connect as `cw_profile` (`infra/dev/postgres/roles.sql`), so it holds locally too, unless
`DB_ROLE=owner`. Settings: `CW_PROFILE_STORE` (`postgres` default, `memory`),
`CW_PROFILE_EVAL_CASES_PATH` (empty keeps the eval seed in the review task only).

## Business API

`/v1/businesses` is the public face of the profile (tags `public` and `businesses`; every route
lists the roles that may call it as `x-roles`). A business is a legal entity with its GSTIN
registrations, and its id is the entity's node id.

- `POST /v1/businesses` (needs `Idempotency-Key`) creates a business from its GSTIN, pre-filling
  it as the prefill route does, or from its PAN alone, stores the first answers and returns the
  first onboarding question. A retry with the same key and body gets the same 201 back with
  `Idempotent-Replayed: true` for 24 hours; the same key with another body is a 422.
- `GET /v1/businesses?q=&limit=&cursor=` lists the tenant's businesses by name, a page at a
  time; `q` matches the name, the PAN or a GSTIN.
- `GET` and `PATCH /v1/businesses/{id}`: a PATCH stores answers across the entity and its
  registrations (a registration answer names its node with `node_id` when there are several)
  and may rename the business. It is all or nothing, and every node that changed publishes
  `profile.updated`.
- `GET /v1/businesses/{id}/onboarding`: the next question with its wording and labelled
  options, and how many of the questions are answered (`application/onboarding.py`,
  `domain/onboarding.py`).
- `POST /v1/businesses/{id}/registrations` (needs `Idempotency-Key`) adds a GSTIN with the
  business's PAN and pre-fills it.

These routes and `GET /v1/ontology` are the profile's part of the public API spec,
`packages/contracts/openapi/public.v1.json` (`make openapi-public` after
`make openapi SERVICE=profile`), and of the generated Python models in
`cw_contracts.rest.public_v1`, which `tests/contract/test_public_client.py` sends and reads.
`x-roles` names `owner`, `staff`, `ca_admin`, `ca_staff` and `compliance_lead`, which a caller an
access token names must hold (see Authentication).

## Plan limits

While the flag `identity.plan_limits` is on for a tenant (`CW_PLAN_LIMITS_ENFORCED=true`,
optionally `CW_PLAN_LIMITS_TENANTS=<ids>`; read through the shared flags reader; default off), a
new GSTIN registration, from `POST /v1/businesses`, `POST /v1/businesses/{id}/registrations` or
`POST /v1/profile/registrations`, is refused once the tenant holds as many as its plan allows:
402 `profile-plan-limit-reached` with `limit` and `used`, and never the GSTIN asked for. A GSTIN
the tenant holds already is found as before, and a business from its PAN alone counts nothing.
The limit is `limits.registrations` of `GET {CW_IDENTITY_URL}/v1/identity/entitlements`, read
with this service's own token (client `profile`, scope `entitlements:read`) before the unit of
work opens, kept 60 seconds per tenant (`infrastructure/entitlements.py`, `HttpEntitlements`).
It fails open: when identity cannot answer, the registration goes ahead with a warning
(`profile_entitlements_unavailable`). Two registrations racing for the last place can both pass;
the limit is commercial, not an invariant. The values are the maintainer's placeholders (see the
identity README).

## Authentication

The caller comes from `py_common.auth` by `CW_AUTH_MODE` (`api/deps.py`):

- `header` (the default): no token is read. The tenant is the `x-tenant-id` header, and
  `changed_by` in a body names who changed a value, as before tokens existed.
- `dual`: a request with a bearer token is served as in `token` mode, and one without it as in
  `header` mode. A bad token is a 401 `auth-token-invalid` whatever the header says.
- `token`: a bearer token is required (401 `auth-token-required`).

With a token, a user's token names the tenant: the header may be left out, and one naming another
tenant is a 403 `auth-tenant-mismatch`. The user needs a tenant member role (`owner`, `staff`,
`ca_admin`, `ca_staff` or `compliance_lead`), else a 403 `auth-forbidden`, and is recorded as who
changed the values (the body's `changed_by` is ignored). A service names the tenant in
`x-tenant-id` and needs the `tenant:act` scope; its changes name no user. `GET /v1/ontology` reads
no token in any mode. `tests/unit/test_auth_mode.py` covers the three modes.

The idempotency keys live in the `idempotency_key` table for 24 hours after the response is
recorded; a request that dies before recording frees its key after 5 minutes. Keys are stored
in their own short transactions (py-common's store mode), because the use cases open their own
units of work. So when the process stops between the business write and recording the
response, a retry after those 5 minutes finds the business or registration and answers 201 with
`created` false rather than the first body. Expired rows are deleted by
`python -m py_common.idempotency purge` run against the profile schema, once a day on a
schedule the deploy wires; nothing runs it yet, and until it does the expired rows only take
space. The list pages on `(name, id)` with the index from migration 0003, and its cursor holds
the id of the last business only, so any name fits the 512-character cursor limit.

`GET /v1/ontology` (tags `public` and `ontology`) is global data and takes no tenant: the
attribute set's version, the wording's version, language and `review_status` (`needs_review`
until an analyst has read it), `operators_by_type` from the kernel's `ALLOWED_OPERATORS`, and
each attribute with its definition, question, help, labelled `values`, `min`, `max` and
`example`. The answer carries an `ETag` and `Cache-Control: max-age=3600`; `If-None-Match` with
the current tag gets a 304.

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

`http` (`infrastructure/lookup_http.py`) asks the provider's taxpayer search:
`GET $CW_PROFILE_GSTIN_LOOKUP_URL?gstin=<GSTIN>` with `CW_PROFILE_GSTIN_LOOKUP_API_KEY` as a
bearer token, waiting at most `CW_PROFILE_GSTIN_LOOKUP_TIMEOUT_SECONDS` (5). A 404 means no such
GSTIN. A timeout, a 5xx or a body that does not map counts as no answer and logs one line, so the
`verify_registration` task opens as in manual mode. `GstnTaxpayerMapper` reads the GSTN
taxpayer-search fields (legal name, trade name, taxpayer type, status, constitution,
registration date, nature of business). Its field names and label tables are marked
`needs_review` until they are checked against the chosen provider's sandbox; a label they do not
hold stays empty. The setting is the flag `profile.gstin_lookup` in `packages/flags`.

Whatever the lookup answers, the GSTIN's first two digits are its state code, so the entity's
`state_codes` gains that code, joined to the codes it already has, with source `derived`. A
code the ontology does not list (97, 99) is skipped. `business_category` is written from the
registry's nature of business only while the flag `profile.gstin_category_prefill` is on for
the tenant (off by default) and the activities map to exactly one category; the mapping is
reviewed by an analyst before the flag goes on.

Both are registry flags (`packages/flags/registry.json`, owner core-product). The service calls
`configure_flags(settings)` when it starts, so with `CW_FLAGS_PROVIDER=env` (the default) the
category pre-fill reads `CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL` (`true` or `false`) and
`CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL__TENANTS` (tenant ids, comma separated; empty means every
tenant), and with `unleash` the Unleash feature `profile.gstin_category_prefill`, targeted by
tenant id. `CW_PROFILE_GSTIN_LOOKUP` stays a setting read at start-up. Turning the HTTP
lookup on for real needs, in order: the provider account, a check of the field names and label
tables against the provider's sandbox (then `MAPPING_REVIEW_STATUS` becomes `reviewed`), and
`CW_PROFILE_GSTIN_LOOKUP=http` with the URL and the key (a secret).

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

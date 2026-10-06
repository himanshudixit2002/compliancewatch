# contracts package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7 (event contract rules), 10, 13 and 14.

- **Owns:** OpenAPI specs (per service, and the merged public API spec with its changelog), event schemas (JSON Schema), generated clients (Python event and REST models, TypeScript event types), and the event changelog
- **Owning team:** Platform and Infrastructure (custodian); every consuming team reviews a contract change
- **Consumes:** n/a
- **Emits / publishes:** Versioned contracts (semver); services pin the versions they consume

## Layout

```
openapi/                 # OpenAPI 3.1 specs, public /v1 and internal service APIs
  llm-gateway.v1.json      # services/llm-gateway
  profile.v1.json          # services/profile
  identity.v1.json         # services/identity
  notification.v1.json     # services/notification
  rulebook.v1.json         # services/rulebook
  obligation.v1.json       # services/obligation
  qa.v1.json               # services/qa
  public.v1.json           # the public API: every operation tagged public, merged (make openapi-public)
  public.meta.json         # the public spec's info: title, description and version
  CHANGELOG.md             # one section per version of the public API
  clients.json             # the specs that get generated Python REST models (today: public)
  BREAKING.md              # deliberate breaking changes, one row per break of an operation, each with an ADR
consumers/               # consumer contracts: <consumer>/<provider>.json, recorded HTTP calls both sides replay (consumers/README.md)
events/
  schemas/               # JSON Schema 2020-12: envelope.v1.json and one <topic>.v1.json per event
  examples/<topic>/      # golden messages (envelope + payload) every check replays
  CHANGELOG.md           # one line per topic per version
scripts/
  generate_events.py     # make contracts: writes both event clients below
  generate_rest.py       # make contracts: the Python REST models of the specs in openapi/clients.json
  build_public_openapi.py    # make openapi-public: public.v1.json from the service specs, with the API rules
  openapi_ts.mjs         # make openapi-ts: writes clients/typescript/openapi from the specs
  check_compat.py        # CI: backward compatibility against the base branch
  check_openapi_coverage.py  # make openapi-check: a service with API routes commits its spec and test
  check_openapi_compat.py    # CI: the OpenAPI specs break no client of the base branch
  check_topics.py        # make contracts-check: every event topic in code has its schema
clients/python/          # compliancewatch-contracts (import cw_contracts): generated pydantic v2 models,
                         # events/ per topic and rest/public_v1.py for the public API
clients/typescript/
  events/                # generated .d.ts per topic plus index.ts (EVENT_TOPICS)
  openapi/               # generated .d.ts per spec plus index.ts (OPENAPI_SERVICES)
```

## OpenAPI specs

A spec is generated from the running service, committed here, and reviewed like code: the diff in
the pull request is the contract change. Each service's `tests/contract/test_openapi.py` fails
when the served schema and the committed file differ, so an API change without a spec change
cannot pass `make test`.

```bash
make openapi SERVICE=llm-gateway   # writes openapi/llm-gateway.v1.json (indent 2, sorted keys)
```

Two gates keep the specs honest. `make openapi-check` (the python job and `make check`) imports
each service's app and fails when it serves more than `/health`, `/ready`, `/v1/<service>/ping`
and the docs pages without a committed spec, or has a spec without
`tests/contract/test_openapi.py`. On a pull request the contracts job runs
`scripts/check_openapi_compat.py` against the base branch (`make openapi-compat BASE=origin/main`
locally). After resolving `$ref` it fails on a removed path, operation or 2xx response, a response
property or media type that went away, a request body, property or parameter that became
required, a narrowed request enum, or a type change. Specs new on the branch are skipped. A
deliberate break gets a row in `openapi/BREAKING.md` (spec, operation, reason, ADR) in the same
pull request.

The specs are also tested against their services. Each service with a spec has
`tests/contract/test_api_properties.py`: schemathesis generates valid and invalid requests from
the served schema, sends them in process with a tenant header, and requires that no response is
a server error and that each status code, content type and body is one the spec documents. Only
the operations listed in the file's `OPERATIONS` run, so the change that adds an operation opts
it in; an operation that cannot pass yet sits in `EXCLUDED` with the reason. CI runs 25
derandomized examples per operation. The nightly workflow runs 200 random ones
(`HYPOTHESIS_PROFILE=nightly uv run pytest -m contract`); a failure there opens the
`nightly-failure` issue, and the run's log holds the example that reproduces it.

The files are generated JSON: prettier ignores `openapi/` and nobody edits them by hand. Every
service shares one error shape, `Problem` (RFC 9457 problem details from py-common), published
under `components.schemas` and referenced by each route's error responses. The description of
each problem response is the interpreter's `http.HTTPStatus` phrase, so a Python minor bump that
rewords a phrase may require regenerating the specs.

### TypeScript types from the specs

`make openapi-ts` runs `scripts/openapi_ts.mjs`, which reads every service spec,
`openapi/<service>.v1.json`, and writes `clients/typescript/openapi/<service>.v1.d.ts` with
`openapi-typescript`'s programmatic API (`paths`, `components`, `operations`; alphabetised; a
property with a default is optional, because pydantic leaves it out of `required` and the services
drop null fields from a `Problem`), plus an `index.ts` that re-exports each file as a namespace
(`identity`, `llmGateway`, `notification`, `obligation`, `profile`, `qa`, `rulebook`) and lists
the services in `OPENAPI_SERVICES`. `public.v1.json` is not a service and gets no file: it is the
facade built from the service specs (below), each of its operations is already typed from its
service's own spec, and the web app calls each service by that spec. The output is formatted with
prettier and committed; stale files for a spec that went away are removed. `make openapi-ts-check`
(part of `make check`) regenerates in memory and fails on a missing, stale or differing file, so a
spec change lands together with its types. The web app imports them type-only, `import type {
profile } from "@compliancewatch/contracts/openapi"`, and binds them to its `openapi-fetch`
clients on the server (`apps/web/src/server/api`); its seed script (`apps/web/scripts/seed`) binds
the same types to its own clients. Nothing from this package runs in a browser (ADR-019). There is
no generated HTTP client: the request layer is the app's own (`docs/web/data-layer.md`), so the
package stays types and schemas. A spec that is new or changed needs `make openapi-ts` in the same
pull request; `make openapi-ts-check` runs in `make check` locally and in the `web-e2e` CI job.

## The public API spec

`public.v1.json` is the API that clients outside the platform call (guide section 10): the web
app, the WhatsApp bot, partners. Nobody writes it by hand. A service puts an operation in it by
tagging the route `public` (FastAPI `tags=["public", ...]`), and `make openapi-public` merges
those operations from the committed service specs. Each operation keeps what its service
documents and gains `x-service`, the service that serves it, which the gateway and the combined
app route by. Only the components the operations reach are copied; identical ones are shared, and
a name two services use for different schemas gets each service's name as a prefix
(`ProfileProblem`), with every reference following the rename. The same path and method in two
services, or an `operationId` used twice, fails the build. The spec's `info` comes from
`public.meta.json`, and every operation requires the `bearerAuth` scheme, the identity
service's access token; while `CW_AUTH_MODE` is `header`, the default, the services read the
tenant from the `x-tenant-id` header instead.

The build also holds each public operation to the API rules and fails with one line per
operation that breaks one:

- `x-roles` lists the roles that may call it: the tenant members' `owner`, `staff`, `ca_admin`,
  `ca_staff` or `compliance_lead`, and the regulatory team's `analyst`, `reviewer` or `admin`,
  which a read of the rulebook names beside the members (the identity service will enforce them;
  until then they are metadata);
- every documented 4xx and 5xx response is a problem document (`application/problem+json`), and
  there is at least one;
- a POST that answers 201 declares the `Idempotency-Key` header (`py_common.idempotency`);
- a GET that answers a page (`items` and `next_cursor`) declares the `limit` and `cursor` query
  parameters (`py_common.pagination`).

The version in `public.meta.json` follows semver: a new operation or optional field is a minor
bump, wording a patch, and a break a major bump with a new `public.v2.json`. The change that
bumps it adds a section to `openapi/CHANGELOG.md`, and the build fails while the current version
has none. `make contracts-check` fails when the committed `public.v1.json` differs from the
build, and `check_openapi_compat.py` compares it with the base branch like every other spec, so a
break of a public operation needs its row in `BREAKING.md` too.

Adding a public route: tag it `public`, give it `openapi_extra={"x-roles": [...]}` and its
problem responses, run `make openapi SERVICE=<name>` and then `make openapi-public`, bump the
version with a changelog section, and commit the service spec, `public.v1.json` and the
regenerated REST models together. A schema whose name the public spec already gives another
service's schema is renamed in its own service first (qa's cited clause became
`AnswerCitationOut` beside the obligation service's `CitationOut`): left alone, the build would
prefix both, renaming the public one, which breaks generated clients. A public path may sit under
its service's own prefix (`/v1/qa`, `/v1/notification/bulk`) or outside every prefix
(`/v1/businesses/{business_id}/obligations`); the deployable routes both (composition/mvp).

## Events

Twenty-one topics have a schema: `document.discovered`, `document.parsed`,
`document.classified`, `rule.candidate.created`, `rule.rejected`, `rule.published`,
`rule.superseded`, `rule.withdrawn`, `rule.deadline_changed`, `profile.updated`,
`applicability.decided`, `obligation.created`, `obligation.due_soon`, `obligation.closed`,
`obligation.rescheduled`, `notification.sent`, `notification.failed`, `tenant.created`,
`tenant.deletion.requested`, `user.role.changed` and `eval.run.completed`. The gateway's `llm.call.completed` and
`llm.budget.alarmed` are still log lines and get a schema when they gain a consumer; until then
they are listed, with the reason, in `LOG_ONLY_TOPICS` in `scripts/check_topics.py`.

A message on the bus is the envelope (`events/schemas/envelope.v1.json`): `event_id`, `topic`,
`schema_version`, `occurred_at`, `tenant_id` (null for regulatory events), `correlation_id`,
`causation_id` and `payload`. Each topic schema describes the payload only. Consumers decode the
envelope, dispatch on `topic`, and validate `payload` with the topic's model at that
`schema_version`. `py_common.events` builds and parses the envelope; `py_common.outbox` writes
and relays it (ADR-005).

Rules, checked in CI:

- Schema files are `<topic>.v<major>.json`, JSON Schema 2020-12, with `$id`
  `urn:compliancewatch:event:<topic>:v<major>`, `x-version` (semver), `x-producer` and
  `x-tenant-scoped`. Every property has a description.
- Payloads are tolerant readers: no `additionalProperties: false`, so a producer can add an
  optional field (minor bump) without breaking an older consumer. A removed or renamed field,
  a new required field or a narrowed enum is a breaking change: a new `v<major>` file next to
  the old one, which stays until every consumer has moved, plus an ADR.
- Every event class in code has its schema. `scripts/check_topics.py` (part of
  `make contracts-check`) reads `services/*/src` and `packages/*/src` without importing them,
  finds each class that sets `topic: ClassVar[str]`, and requires `<topic>.v<major>.json` with
  `x-version` equal to the class's `schema_version`. A `LOG_ONLY_TOPICS` entry fails once its
  topic gains a schema or loses its class, so the commit that adds the schema removes the entry.
- Every version has a line in `events/CHANGELOG.md` and every topic at least one example under
  `events/examples/<topic>/`. The examples are what the backward-compatibility check replays.
- The clients are generated, never edited: `make contracts` (datamodel-code-generator for
  Python, json-schema-to-typescript for TypeScript, then this package's own registry and index).
  `make contracts-check` fails when the committed clients differ from the schemas.
- On a pull request, `scripts/check_compat.py` validates the base branch's examples against the
  branch's schemas and refuses a removed file, a downgraded version or a content change without
  a version bump; the dev-stack job registers the base version of each changed schema in the
  Redpanda schema registry with `BACKWARD` compatibility and checks the new one with
  `rpk registry schema check-compatibility`.

Adding a topic: write the schema and an example, add the CHANGELOG line, run `make contracts`,
commit the generated files, then declare `topic` and `schema_version` on the producer's event
class and write it through `OutboxWriter`. `packages/py-common/README.md` has the producer and
consumer side.

## Clients

`clients/python` is the uv workspace member `compliancewatch-contracts`; services import
`cw_contracts.events` (`TOPICS`, `EventEnvelopeV1`, one model per topic). It depends on pydantic
only, and import-linter keeps it that way. `clients/typescript/events` exports one interface per
topic, `EventEnvelope` and the `EVENT_TOPICS` constant; both are regenerated by `make contracts`.
`clients/typescript/openapi` holds the types generated from the OpenAPI specs by
`make openapi-ts` (above). The package's `typecheck` script runs `tsc` over both directories, and
`package.json` exports them as `@compliancewatch/contracts/events` and
`@compliancewatch/contracts/openapi`.

`cw_contracts.rest` holds the REST models. `generate_rest.py` runs `datamodel-codegen` over each
spec that `openapi/clients.json` lists (today the public spec alone) and writes one module per
spec, `cw_contracts/rest/public_v1.py`, with a pydantic model for every schema: the request
bodies (`BusinessIn`, `BusinessPatchIn`, `RegistrationAddIn`, `AskIn`, `BulkNotificationIn` and
the rest), the responses and `Problem`. An enum stays an enum class even with one value
(`BulkKind`), so a value added later is a new member. The module's docstring names the spec
version it came from. Response models ignore fields they do
not know, so a client keeps working when a minor version adds one; request models refuse
unknown fields, as the services do. `make contracts` and `make openapi-public` regenerate them,
and `make contracts-check` fails when the committed module differs. The profile service's
`tests/contract/test_public_client.py` sends requests built from these models and reads every
answer with them. TypeScript has types only (`clients/typescript/openapi`, above), no generated
client.

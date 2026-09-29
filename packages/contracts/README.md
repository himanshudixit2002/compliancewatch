# contracts package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7 (event contract rules), 10, 13 and 14.

- **Owns:** OpenAPI specs, event schemas (JSON Schema), generated clients (py + ts), and the event changelog
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
  BREAKING.md              # deliberate breaking changes, one row per break of an operation, each with an ADR
events/
  schemas/               # JSON Schema 2020-12: envelope.v1.json and one <topic>.v1.json per event
  examples/<topic>/      # golden messages (envelope + payload) every check replays
  CHANGELOG.md           # one line per topic per version
scripts/
  generate_events.py     # make contracts: writes both clients below
  check_compat.py        # CI: backward compatibility against the base branch
  check_openapi_coverage.py  # make openapi-check: a service with API routes commits its spec and test
  check_openapi_compat.py    # CI: the OpenAPI specs break no client of the base branch
  check_topics.py        # make contracts-check: every event topic in code has its schema
clients/python/          # compliancewatch-contracts (import cw_contracts): generated pydantic v2 models
clients/typescript/      # generated .d.ts per topic plus index.ts (EVENT_TOPICS)
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

## Events

Fourteen topics have a schema: `document.discovered`, `document.parsed`,
`rule.candidate.created`, `rule.published`, `rule.superseded`, `profile.updated`,
`applicability.decided`, `obligation.created`, `obligation.due_soon`, `obligation.closed`,
`obligation.rescheduled`, `notification.sent`, `notification.failed` and
`tenant.deletion.requested`. The gateway's `llm.call.completed` and `llm.budget.alarmed` are
still log lines and get a schema when they gain a consumer; until then they are listed, with the
reason, in `LOG_ONLY_TOPICS` in `scripts/check_topics.py`.

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
topic, `EventEnvelope` and the `EVENT_TOPICS` constant; the package's `typecheck` script runs
`tsc` over them. Both are regenerated by `make contracts`.

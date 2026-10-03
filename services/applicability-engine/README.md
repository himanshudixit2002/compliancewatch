# applicability-engine service

Part of the ComplianceWatch monorepo. **Deterministic evaluation of one rule version against one business, stored append-only with its event; no LLM judge, no fan-out and no event consumers yet.**
Design reference: Project Foundation guide, sections 7, 8, 11 and 14.

- **Owns:** ApplicabilityDecisions: coarse filter by regulator and attribute index, per-business predicate evaluation, LLM-judged free-text predicates with confidence, Temporal fan-out in batches of 1,000
- **Owning team:** Core Product (deterministic path and fan-out); AI Platform owns the LLM evaluator (guide section 14)
- **Consumes:** rule.published (fan-out); profile.updated (single business); rulebook read API; LLM gateway API
- **Emits / publishes:** applicability.decided

## What is here

- `domain/evaluation.py`: evaluates a rule version's specification (the kernel's predicate tree)
  against a profile snapshot with the packaged ontology. Every predicate is judged, left to
  right, and three-valued logic combines them. Free text, an attribute the profile has not set,
  an attribute not in the ontology, or a comparison the ontology refuses is `unsure` with a
  reason, never a guess. The decision has confidence 1 when the tree resolves to `applies` or
  `not_applicable` and 0 when it is `unsure`, which sets `needs_review`.
- `application/evaluate.py`: `EvaluateRule` reads the rule version from the rulebook
  (`GET /v1/rulebook/rule-versions/{id}`; only a published one is evaluated) and the profile
  snapshot from the profile service (`GET /v1/profile/nodes/{id}/snapshot`, for the financial
  year asked or the current one in India), and appends a `Decision` with its
  `applicability.decided` event in one transaction. Recomputing appends another decision.
- `application/queries.py`: `ListDecisions` (a business's decisions, newest first, optionally of
  one rule version, keyset paged) and `ReadDecision`.
- `infrastructure/`: the HTTP clients (`profile_client.py`, `rulebook_client.py`; a 404 is
  `None`, anything else unexpected is `DependencyUnavailableError`, 503), the Postgres unit of
  work (`app.tenant_id` set per transaction, events to the outbox on the same connection) and
  its in-memory twin. `applicability_engine.testing` has in-memory readers and builders.
- `migrations/versions/20261001_0001_applicability_decisions.py`: `applicability_decision` with
  forced row-level security and an append-only trigger (DELETE only under `app.erasure=on`),
  the outbox and `idempotency_key`.

Routes, for the request's tenant (`api/deps.py`):

- `POST /v1/applicability-engine/businesses/{business_id}/decisions` with `rule_version_id` and
  an optional `fy`: evaluate and store; requires `Idempotency-Key`. 404 for an unknown rule
  version or business, 409 for a version that is not published, 503 when a dependency fails.
- `GET /v1/applicability-engine/businesses/{business_id}/decisions`: newest first, `limit` and
  `cursor` (py_common.pagination), optional `rule_version_id`.
- `GET /v1/applicability-engine/decisions/{decision_id}`: one decision with every predicate's
  outcome, confidence and reason.

Not built yet (WP22 and WP26): the LLM evaluator for free-text predicates, the golden set, the
consumers of `rule.published` and `profile.updated`, the coarse filter and the fan-out.

## Layout

```
src/applicability_engine/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters
  main.py          # composition root: create_app(...) from py-common
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
make migrate SERVICE=applicability-engine
make run SERVICE=applicability-engine           # http://localhost:8004/health, /ready, /v1/applicability-engine/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/applicability-engine/Dockerfile -t compliancewatch-applicability-engine .
```

Package `applicability_engine`, dev port 8004, Postgres schema `applicability`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

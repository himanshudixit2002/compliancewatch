# obligation service

Part of the ComplianceWatch monorepo. **Domain, use cases and the Postgres unit of work exist; no API beyond the health routes and no event consumer yet.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Obligations, evidence metadata, append-only audit log; builds obligations from the RuleVersion template, computes due dates, schedules reminders
- **Owning team:** Core Product (guide section 14)
- **Consumes:** applicability.decided; user actions
- **Emits / publishes:** obligation.created, obligation.rescheduled, obligation.closed (through the outbox); obligation.due_soon arrives with the reminder scheduler

## What is here

- `domain/model.py`: the `Obligation` aggregate, one per business and rule version, plus one
  per period when the rule recurs (ADR-015). `start`, `reschedule` and `close` return the new
  obligation and the event that records it; a closed obligation never changes again.
- `application/materialise.py`: `MaterialiseObligations` creates the obligations a rule
  version implies for a business, idempotent on (business, rule version, period), inside a
  rolling window of periods; due dates are the end of the due day in India Standard Time.
- `application/changes.py`: `ApplyDeadlineChange` moves open obligations of a period and
  publishes `obligation.rescheduled`; `WithdrawRule` closes them with `rule_withdrawn`;
  `CloseObligation` closes one for a user's reason.
- `infrastructure/repository.py`: `PostgresUnitOfWorkFactory` opens one transaction per call
  with the `app.tenant_id` setting that the row-level security policy reads, and writes events
  to the outbox on the same connection. `infrastructure/memory.py` is the in-memory twin for
  tests; `obligation.testing` has sample builders.
- `migrations/versions/20260928_0001_obligations.py`: the `obligation` table with row-level
  security enabled and forced, the outbox and the consumer inbox tables (py-common helpers).

The caller of the use cases is the applicability engine's decision consumer, which lands with
the profile and engine work; until then the use cases are exercised by the tests and by hand.

Row-level security only binds non-superuser roles: a superuser bypasses every policy whatever
the table says. The dev stack's `cw` user is the container's superuser, so locally the policy
is present but not enforced; the integration test creates a plain role and proves the isolation
through it, and every deployment must give the service a role that is neither a superuser nor
the table owner. The policy reads `app.tenant_id` through `NULLIF(current_setting(...), '')`
because Postgres reports a custom setting as an empty string between transactions once it has
been used in a session.

## Layout

```
src/obligation/
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
make migrate SERVICE=obligation
make run SERVICE=obligation           # http://localhost:8005/health, /ready, /v1/obligation/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/obligation/Dockerfile -t compliancewatch-obligation .
```

`CW_OBLIGATION_STORE=memory|postgres` picks the store (memory for tests and demos; the readiness check pings whichever is wired). Package `obligation`, dev port 8005, Postgres schema `obligation`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

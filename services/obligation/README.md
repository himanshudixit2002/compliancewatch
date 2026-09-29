# obligation service

Part of the ComplianceWatch monorepo. **Domain, use cases, the Postgres unit of work and a read route exist; no write API and no event consumer yet.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Obligations, evidence metadata, the append-only change log of every obligation (`obligation_change`); builds obligations from the RuleVersion template, computes due dates, schedules reminders
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
- `domain/history.py` and `application/audit.py`: the change log (ADR-015, every change writes
  an audit row). Every use case above publishes through `audit.record(uow, event, after)`,
  which also appends an `ObligationChange` to `uow.history`: kind `created`, `rescheduled` or
  `closed`, the previous and new due dates, the status after the change, the reason
  (`deadline_extended`, `corrected`, `manual`, or a closure reason), the rule version that
  caused it, the actor and the correlation id. The change's id is the event's id, and it is
  written on the same connection as the event's outbox row, so the two commit or roll back
  together. A use case that leaves an obligation unchanged, or skips a closed one, writes
  neither. This table is the single history of an obligation; later kinds (started, completed,
  assigned) widen `ChangeKind` and its CHECK constraint. The change log has no read route yet.
- `application/queries.py`: `ListObligations` reads one business's obligations in any status,
  optionally due inside a `DueWindow` (days in India, both ends included, at most 366 days) and
  of one rule version; due date first (undated last), then period start, creation and id; at
  most 500.
- `infrastructure/repository.py`: `PostgresUnitOfWorkFactory` opens one transaction per call
  with the `app.tenant_id` setting that the row-level security policy reads, and writes events
  to the outbox on the same connection. `infrastructure/memory.py` is the in-memory twin for
  tests; `obligation.testing` has sample builders.
- `migrations/versions/20260928_0001_obligations.py`: the `obligation` table with row-level
  security enabled and forced, the outbox and the consumer inbox tables (py-common helpers).
- `migrations/versions/20260929_0002_obligation_change.py`: the `obligation_change` table,
  with the same forced row-level security (`py_common.migrations.enable_tenant_rls`) and an
  append-only trigger (`create_append_only_guard(..., allow_erasure_delete=True)`): UPDATE is
  always refused, and DELETE only in a transaction that has set `app.erasure` to `on`. A tenant
  erasure (not built yet; a later work package adds it) must set `app.erasure=on` and delete the
  change rows before the obligations.

The caller of the write use cases is the applicability engine's decision consumer, which lands
with the profile and engine work; until then they are exercised by the tests and by hand. The
rulebook now publishes `rule.deadline_changed`, `rule.withdrawn` and `rule.superseded`; the
consumer that turns them into `ApplyDeadlineChange` and `WithdrawRule` for every tenant's open
obligations is not built yet, because it needs a cross-tenant design under row-level security.

## API

| Route | What it does |
| --- | --- |
| `GET /v1/obligation/obligations?business_id=&due_from=&due_to=&rule_version_id=` | The business's obligations with `obligation_id, business_id, rule_version_id, decision_id, title, steps, evidence_type, period_label, period_start, period_end, due_at, status, closed_at, closed_reason`. `due_from` and `due_to` are days in India, both included; an obligation without a due date is left out when either is given. `due_at` is the end of the due day in India, in UTC; the period is half-open. Needs `x-tenant-id` (401 `obligation-tenant-required` without it); a window that ends before it starts, spans more than 366 days or ends on 9999-12-31 (there is no day after it) is 422 `obligation-window-invalid` |

The tenant header stands in for a token until the identity service issues them (ADR-014), and
the unit of work sets it for row-level security, so a read never sees another tenant's rows.
The spec is committed at `packages/contracts/openapi/obligation.v1.json`
(`make openapi SERVICE=obligation`) and pinned by `tests/contract/test_openapi.py`.

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
  api/             # router.py (the read route), schemas.py (ObligationOut), deps.py (tenant header, wiring)
  application/     # materialise.py, changes.py, queries.py
  domain/          # model.py (Obligation, DueWindow), events.py, errors.py, repository.py (protocols)
  infrastructure/  # models.py, repository.py (Postgres unit of work with the outbox), memory.py
  wiring.py        # what the api layer gets from the composition root
  main.py          # composition root: wire(settings), build_app(settings), problem statuses
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with fakes; no I/O
  integration/     # testcontainers: postgres, kafka
  contract/        # test_openapi.py: the served schema equals the committed spec; test_events.py: the event payloads
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=obligation
make run SERVICE=obligation           # http://localhost:8005/health, /ready, /v1/obligation/obligations
make test                         # unit + contract tests with the coverage gate
docker build -f services/obligation/Dockerfile -t compliancewatch-obligation .
```

`CW_OBLIGATION_STORE=memory|postgres` picks the store (memory for tests and demos; the readiness check pings whichever is wired). Package `obligation`, dev port 8005, Postgres schema `obligation`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

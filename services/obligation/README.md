# obligation service

Part of the ComplianceWatch monorepo. **Domain, use cases, the Postgres unit of work, a read route and the worker (the applicability.decided consumer and the reminder sweep) exist; no write API yet.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Obligations, evidence metadata, the append-only change log of every obligation (`obligation_change`); builds obligations from the RuleVersion template, computes due dates, schedules reminders
- **Owning team:** Core Product (guide section 14)
- **Consumes:** applicability.decided; user actions
- **Emits / publishes:** obligation.created, obligation.rescheduled, obligation.closed and obligation.due_soon (through the outbox)

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
- `application/decisions.py`: `ApplyDecision` acts on one applicability decision. `applies`
  without `needs_review` materialises the business's obligations of the rule version, read from
  the rulebook (`domain/ports.py` `RuleVersionReader`, `infrastructure/rulebook_client.py`), as of
  the day of the decision in India; `not_applicable` without `needs_review` closes the business's
  open obligations of the rule version with `profile_changed`; a decision that needs review
  changes nothing. Both are idempotent under redelivery. A closed obligation stays closed: a
  later `applies` only creates periods that have no obligation yet.
- `domain/reminders.py` and `application/reminders.py`: `SendDueReminders`, the reminder sweep.
  For every tenant in the tenant directory it opens one unit of work and publishes
  `obligation.due_soon` for each open obligation whose `days_left` falls in a threshold of
  `REMINDER_DAYS` (7, 3, 1) it has not been reminded at for its current due date, recording an
  `obligation_reminder` row with the outbox row. A sweep that first sees an obligation late sends
  only the most urgent reminder; a rescheduled obligation is reminded again against its new date;
  `reminder_index` counts the obligation's reminders and never repeats. A tenant whose unit fails
  rolls back alone and is retried by the next sweep.
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
- `migrations/versions/20261004_0003_obligation_reminders.py`: `obligation_reminder` (one row per
  reminder, unique per obligation, due date and threshold and per obligation and index, forced
  row-level security, cascades with its obligation) and `obligation_tenant`, the tenant
  directory: a routing directory in infra/scripts/migration_lint.toml whose ids every session
  may read while every write passes the tenant policy. The repository records the unit's tenant
  when it adds the tenant's first obligation; `PostgresTenantDirectory` reads it for the sweep.
- `worker.py`: `python -m obligation.worker` (`make worker SERVICE=obligation`, needs
  `CW_OBLIGATION_STORE=postgres`). The consumer group `obligation.decisions` reads
  `applicability.decided` and applies each decision in the consumer's own transaction
  (`PostgresUnitOfWorkFactory.on_connection`), so the obligations, their outbox and change rows
  and the `processed_event` row commit together; what it cannot apply goes to
  `applicability.decided.obligation.decisions.dlq` after the retries. The reminder sweep runs
  every `CW_OBLIGATION_SWEEP_INTERVAL_SECONDS` (3600) when `CW_OBLIGATION_SWEEP_ENABLED` (flag
  `obligation.reminder_sweep`, off by default) is on. The outbox relay runs on its own
  (`make relay SERVICE=obligation`).

The rulebook publishes `rule.deadline_changed`, `rule.withdrawn` and `rule.superseded` without a
tenant; the consumer that turns them into `ApplyDeadlineChange` and `WithdrawRule` for every
tenant's open obligations is not built yet. It can iterate the `obligation_tenant` directory one
tenant unit at a time, the way the reminder sweep does, without relaxing row-level security.

## API

| Route | What it does |
| --- | --- |
| `GET /v1/obligation/obligations?business_id=&due_from=&due_to=&rule_version_id=` | The business's obligations with `obligation_id, business_id, rule_version_id, decision_id, title, steps, evidence_type, period_label, period_start, period_end, due_at, status, closed_at, closed_reason`. `due_from` and `due_to` are days in India, both included; an obligation without a due date is left out when either is given. `due_at` is the end of the due day in India, in UTC; the period is half-open. Needs a tenant (401 `obligation-tenant-required` without one; see below); a window that ends before it starts, spans more than 366 days or ends on 9999-12-31 (there is no day after it) is 422 `obligation-window-invalid` |

Who calls and for which tenant comes from `py_common.auth` by `CW_AUTH_MODE` (`api/deps.py`):

- `header` (the default): the `x-tenant-id` header names the tenant, and no token is read.
- `dual`: a bearer token is verified when the request carries one, and then counts as in
  `token` mode; without one the header counts, as in `header` mode.
- `token`: a bearer token is required (401 `auth-token-required`). A user's token names the
  tenant, and the user needs one of the tenant member roles (owner, staff, ca_admin, ca_staff,
  compliance_lead); an `x-tenant-id` naming another tenant is a 403 `auth-tenant-mismatch`. A
  service (the qa service reading the obligations a question is about) names the tenant in
  `x-tenant-id` and needs the tenant:act scope. Anyone else is a 403 `auth-forbidden`.

The unit of work sets the tenant for row-level security, so a read never sees another tenant's
rows.
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
  api/             # router.py (the read route), schemas.py (ObligationOut), deps.py (caller and tenant, wiring)
  application/     # materialise.py, changes.py, decisions.py, reminders.py, queries.py
  domain/          # model.py (Obligation, DueWindow), events.py, errors.py, reminders.py, ports.py, repository.py (protocols)
  infrastructure/  # models.py, repository.py (Postgres unit of work with the outbox), memory.py, rulebook_client.py
  wiring.py        # what the api layer gets from the composition root
  main.py          # composition root: wire(settings), build_app(settings), problem statuses
  worker.py        # the worker's composition root: components(settings), the decision handler, the sweep job
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
make worker SERVICE=obligation        # the applicability.decided consumer (and the sweep when enabled)
make test                         # unit + contract tests with the coverage gate
docker build -f services/obligation/Dockerfile -t compliancewatch-obligation .
```

`CW_OBLIGATION_STORE=memory|postgres` picks the store (memory for tests and demos; the readiness check pings whichever is wired). Package `obligation`, dev port 8005, Postgres schema `obligation`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

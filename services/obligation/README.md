# obligation service

Part of the ComplianceWatch monorepo. **Domain, use cases, the Postgres unit of work, the read routes, the public API's list of a business's obligations, the tracking routes (status, assignee, comments, each with an Idempotency-Key and an audit row) and the worker (the applicability.decided consumer, the rule events consumer, the reminder sweep and the rolling window) exist.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Obligations, evidence metadata, the append-only change log of every obligation (`obligation_change`); builds obligations from the RuleVersion template, computes due dates, schedules reminders
- **Owning team:** Core Product (guide section 14)
- **Consumes:** applicability.decided; rule.published, rule.superseded, rule.withdrawn and rule.deadline_changed; user actions (start, complete, waive, assign, comment)
- **Emits / publishes:** obligation.created, obligation.rescheduled, obligation.closed and obligation.due_soon (through the outbox)

## What is here

- `domain/model.py`: the `Obligation` aggregate, one per business and rule version, plus one
  per period when the rule recurs (ADR-015), with the profile version of the decision that made
  it (`profile_version`, null for one made before it was kept) and its assignee. `reschedule`
  and `close` return the new obligation and the event that records it; `start` and `assign`
  return the new obligation alone, since no other service acts on them. A closed obligation
  never changes again.
- `application/materialise.py`: `MaterialiseObligations` creates the obligations a rule
  version implies for a business, idempotent on (business, rule version, period), inside a
  rolling window of periods; due dates are the end of the due day in India Standard Time.
- `application/changes.py`: `ApplyDeadlineChange` moves open obligations of a period and
  publishes `obligation.rescheduled`; `WithdrawRule` closes them with `rule_withdrawn`;
  `CloseSupersededPeriods` closes, with `rule_superseded`, the open obligations a superseding
  version takes over (a period that ends after its `effective_from`, a one-off due on that day
  or later, or one without a date) and leaves the earlier ones; `CloseObligation` closes one for
  a user's reason.
- `domain/history.py` and `application/audit.py`: the change log (ADR-015, every change writes
  an audit row). Every use case above publishes through `audit.record(uow, event, after)`,
  which also appends an `ObligationChange` to `uow.history`: kind `created`, `rescheduled` or
  `closed`, the previous and new due dates, the status after the change, the reason
  (`deadline_extended`, `corrected`, `manual`, or a closure reason), the rule version that
  caused it, the actor and the correlation id. The change's id is the event's id, and it is
  written on the same connection as the event's outbox row, so the two commit or roll back
  together. A use case that leaves an obligation unchanged, or skips a closed one, writes
  neither. This table is the single history of an obligation. A person's changes no event records
  are rows too, each with an id of its own (`history.started_change` and `assignment_change`):
  `started`, `assigned` and `unassigned`, the last two naming the assignee before and after; a
  completion or a waiver is a `closed` change with the reason `completed` or `waived_by_user`, and
  `note` keeps what the person said (a waiver's reason). The detail route reads it.
- `domain/comments.py` and `application/tracking.py`: what a tenant's members do with an
  obligation. `ReadObligation` answers it with the facts of its rule version from the
  `rule_version_ref` cache (title, rule key, seed status, the approvers of the round it was
  published from and when), its verified citations, its history and its comments, oldest first;
  when the cache has no row of the version (an obligation made before migration 0004), it reads
  the rulebook with no unit of work open and fills the cache, as the decision consumer does.
  `ChangeStatus` starts (open to in progress), completes or waives one (a reason of at least ten
  characters), the row locked for the change: a closed obligation is 409 `obligation-closed`, a
  move the kernel's table refuses (starting one in progress) 422 `invalid-transition`.
  Completing and waiving publish obligation.closed, which the notification service sends nothing
  for; starting publishes nothing. `AssignObligation` gives an open one to a user of the tenant,
  or to nobody: when a verified token named the caller, the identity service is asked first,
  with no unit of work open, whether the user is an active user of the tenant
  (`infrastructure/identity_client.py`, `GET /v1/identity/users/{user_id}/membership` with this
  service's token; 422 `obligation-assignee-unknown` when not, 503 `identity-unavailable` when it
  cannot say). Without a token (`header` mode, or `dual` without one) nobody can be held to the
  tenant's users, so the assignee is kept as the request names it: the local product and the web
  stack run that way, and token mode, as in production, always checks. `AddComment` adds a comment
  by the caller, on an open or a closed obligation. Every change writes an `audit.event` row in its
  unit of work (`py_common.audit`): `obligation.status.start`, `.complete` and `.waive` with the
  reason, `obligation.assign` with the assignee before and after, and `obligation.comment` naming
  the comment, never its text; the actor is the user a token named, with their roles, else
  `system:obligation`.
- `application/decisions.py`: `ApplyDecision` acts on one applicability decision in two steps:
  `plan` reads the rule version (`domain/ports.py` `RuleVersionReader`,
  `infrastructure/rulebook_client.py`) with no transaction open, and `apply` writes. `applies`
  without `needs_review` materialises the business's obligations of the rule version as of the
  day of the decision in India, behind the guard (below); `not_applicable` without
  `needs_review` closes the business's open obligations of the rule version with
  `profile_changed`; a decision that needs review changes nothing. Each applies or
  not_applicable decision is recorded as the business's latest for the version
  (`obligation_decision`), and one made before the latest recorded changes nothing (`stale`).
  Both are idempotent under redelivery. A closed obligation stays closed: a later `applies` only
  creates periods that have no obligation yet.
- `domain/rule_versions.py` and `application/guard.py`: the rule version cache and the guard.
  `RuleVersionRef` is what the service keeps of a version (`rule_version_ref`): rule key, status,
  title, effective dates, seed status, the approvers of the round it was published from, when it
  was published, its verified citations and when the rulebook was read. A status only moves past
  publication and an `effective_to` only moves earlier (`merge`). `guard.admit` merges the version
  as the reader fetched it into the cache, filling it on a miss, and judges what the cache then
  holds: a withdrawn version makes nothing (`rule_withdrawn`), nor does one without a verified
  citation (`uncited`; every obligation carries at least one), and a version cut short by a
  replacement makes only the periods it still governs, the ones whose last day it is in force on
  (`rule_superseded` for the rest). The cache row stays locked until the transaction ends, so a
  decision and a rule event about one version run one after the other: an `applicability.decided`
  that arrives after the withdrawal (a fan-out batch in flight, a consumer behind on its topic,
  a read kept from a minute ago) is refused, and one applied just before it is closed by it.
- `application/rule_events.py`: `RuleEvents`, what the consumer of the rule events does.
  `rule.published` refreshes the cache only (the engine fans the version out, and the obligations
  arrive with its decisions); `rule.withdrawn` caches the version as withdrawn and runs
  `WithdrawRule` for every tenant of the directory; `rule.superseded` caches it as superseded,
  ending on the event's `effective_from`, and runs `CloseSupersededPeriods`; `rule.deadline_changed`
  runs `ApplyDeadlineChange` for the event's period. A withdrawal or a supersession reads the
  version fresh; when the rulebook cannot answer, the cached row is moved on its own, and with
  neither the event fails and is retried. Every use case is idempotent, so a replayed event
  changes nothing more.
- `application/window.py`: `RollWindow`, the rolling window. For every tenant (or those named)
  and every business whose latest decision of a recurring rule version applies, it materialises
  the window as of today in India behind the guard, so the periods that entered the window since
  a decision or a run last made them get their obligations; reads with no unit of work open.
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
  most 500. `ListBusinessObligations` serves the public list a page at a time: the obligations of
  some statuses (any when none is named) in a `DueWindow`, by due date (undated last) and id,
  after a keyset (`domain/repository.py` `ListingAfter`, the due date and id of the last one on
  the previous page), each with the cached facts of its rule version (`rule_version_ref`; none for
  a version not cached yet, which the detail reads from the rulebook). Its unit of work reads
  under row-level security, so another tenant's obligations never come back; a page with nothing
  on it then asks the profile service, with no unit of work open, whether the business is a node
  of the tenant at all (`domain/ports.py` `ProfileNodes`, `infrastructure/profile_client.py`,
  `GET /v1/profile/nodes/{node_id}` with this service's token): 404
  `obligation-business-not-found` when it is not, 503 `profile-unavailable` when profile cannot
  say. A business with obligations on the page is the tenant's, so profile is not asked then.
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
- `migrations/versions/20261006_0004_rule_version_cache.py`: `rule_version_ref`, the rule
  version cache, rule-level and so without tenant_id or row-level security (exempt in
  infra/scripts/migration_lint.toml), with the verified citations as JSON; and
  `obligation_decision`, the latest applies or not_applicable decision per business and rule
  version under the tenant policy, which the rolling window reads. No backfill: a business
  decided before this release has its window rolled from its next decision on.
- `migrations/versions/20261006_0005_obligation_tracking.py`: `profile_version` and `assignee_id`
  on `obligation` (and `profile_version` on `obligation_decision`, which the rolling window gives
  the periods it makes); the change kinds `started`, `assigned` and `unassigned` with the
  assignee columns and `note` on `obligation_change`; `obligation_comment` (forced row-level
  security, append-only with the erasure switch like the change log, RESTRICT to its obligation,
  a body of 1 to 2,000 characters); and py-common's `idempotency_key`, which the daily purge of the
  worker clears. Expand-only; the downgrade narrows the kind check NOT VALID, so it deletes no
  change. A tenant erasure deletes the comments before the obligations.
- `migrations/versions/20261004_0003_obligation_reminders.py`: `obligation_reminder` (one row per
  reminder, unique per obligation, due date and threshold and per obligation and index, forced
  row-level security, cascades with its obligation) and `obligation_tenant`, the tenant
  directory: a routing directory in infra/scripts/migration_lint.toml whose ids every session
  may read while every write passes the tenant policy. The repository records the unit's tenant
  when it adds the tenant's first obligation; `PostgresTenantDirectory` reads it for the sweep.
- `worker.py`: `python -m obligation.worker` (`make worker SERVICE=obligation`, needs
  `CW_OBLIGATION_STORE=postgres`). Both consumers read with no transaction open and then write
  in the consumer's own transaction (`py_common.outbox.read_then_write`,
  `PostgresUnitOfWorkFactory.on_connection`), so everything they change commits with the
  `processed_event` row:
  - group `obligation.decisions` reads `applicability.decided` and applies each decision; a
    guard refusal is logged as `obligation.decision_guarded` (reason, status, end, refused
    periods) and counted in `obligation_guard_refusals_total{reason, source}`; what it cannot
    apply goes to `applicability.decided.obligation.decisions.dlq` after the retries;
  - group `obligation.rules` reads `rule.published`, `rule.superseded`, `rule.withdrawn` and
    `rule.deadline_changed` (no tenant) and applies each to every tenant of the `obligation_tenant`
    directory, one unit of work per tenant on the consumer's connection, each setting its own
    tenant so row-level security holds, logged as `obligation.rule_event`. With
    `CW_OBLIGATION_RULE_EVENTS_ENABLED` (flag `obligation.rule_events`, off by default) off it
    still consumes, so its offsets keep up, and changes nothing. One transaction holds every
    tenant's changes for an event: fine while the tenants are few; per-tenant transactions with
    their own processed mark come later.

  With `CW_OBLIGATION_SWEEP_ENABLED` (flag `obligation.reminder_sweep`, off by default) the
  reminder sweep runs every `CW_OBLIGATION_SWEEP_INTERVAL_SECONDS` (3600) and the rolling window
  daily at 02:30 IST (`obligation.window_rolled`). Both consumers share one rulebook reader,
  which keeps a read for a minute and is read fresh by a rule event, so the decision consumer of
  the same process sees a withdrawal at once. The outbox relay runs on its own
  (`make relay SERVICE=obligation`).
- `sweep.py`: `obligation-sweep --once [--now ISO] [--tenant ID]... [--json]` runs the reminder
  sweep and the rolling window once, with the worker's settings. `--now` runs them as of another
  moment (with its offset) and is refused unless `CW_ENV` is local or test; `--tenant` limits
  both to the tenants named, which is how the local product's check leaves the shared dev
  database's other tenants alone. Exit 0, 1 when a tenant failed, 2 when refused.

The rulebook's `GET /v1/rulebook/rule-versions/{id}` names the approvers of the round a version
was published from (`approved_by`) and when (`published_at`), so the cache gets them from one
read, whichever event reached the service first; the detail carries the citations too, so no
second call to the citations route is needed. A deadline change of a period that has no
obligation yet is not remembered: an obligation made later for that period takes the version's
own due date.

## API

| Route | What it does |
| --- | --- |
| `GET /v1/obligation/obligations?business_id=&due_from=&due_to=&rule_version_id=` | The business's obligations with `obligation_id, business_id, rule_version_id, decision_id, title, steps, evidence_type, period_label, period_start, period_end, due_at, status, closed_at, closed_reason, profile_version, assignee_id`. `due_from` and `due_to` are days in India, both included; an obligation without a due date is left out when either is given. `due_at` is the end of the due day in India, in UTC; the period is half-open. Needs a tenant (401 `obligation-tenant-required` without one; see below); a window that ends before it starts, spans more than 366 days or ends on 9999-12-31 (there is no day after it) is 422 `obligation-window-invalid` |
| `GET /v1/obligation/obligations/{obligation_id}` | One obligation with `rule_version` (rule key, title, status, effective dates, `seed_status` and `reviewed`, false while the seed rule needs review, and `approved_by` with `published_at`: the reviewed-by line; null when the rulebook has no such version), `citations` (verified), `history` (every change, oldest first) and `comments` (oldest first). 404 `obligation-not-found` for another tenant's; 503 `rulebook-unavailable` when the cache lacks the version and the rulebook cannot answer |
| `POST /v1/obligation/obligations/{obligation_id}/status` | `{"action": "start" \| "complete" \| "waive", "reason": ""}`: the obligation after the change. A waiver needs a reason of at least ten characters (422 `request-invalid`); 409 `obligation-closed`, 422 `invalid-transition` |
| `PUT /v1/obligation/obligations/{obligation_id}/assignee` | `{"assignee_id": "<user>" \| null}`: the obligation after the change; the assignee it has already changes nothing. 409 `obligation-closed`; with a verified caller 422 `obligation-assignee-unknown` and 503 `identity-unavailable` |
| `POST /v1/obligation/obligations/{obligation_id}/comments` | `{"body": "..."}` (1 to 2,000 characters once trimmed): 201 with the comment, its author and their label |

The public API (tag `public`, with `x-roles` naming every tenant member role, in
`packages/contracts/openapi/public.v1.json`) lists a business's obligations from 0.4.0:

| Route | What it does |
| --- | --- |
| `GET /v1/businesses/{business_id}/obligations?status=&due_from=&due_to=&limit=&cursor=` | One page (`limit` 1 to 200, 50 by default, and the `next_cursor` of the page before) of the obligations kept for `business_id`, any profile node of the tenant: the business (its legal entity, the id of `/v1/businesses`), one of its registrations (where a GSTIN's returns are kept) or a location; the web app merges the nodes of a business. By due date, undated last, then by id. `status` keeps the statuses named (repeat it for several); `due_from` and `due_to` keep the obligations due on those days in India, as above (422 `obligation-window-invalid`). Each item is an obligation with `rule_version` (as in the detail; null for a version not cached yet) and `citations` (verified), without history or comments. 404 `obligation-business-not-found` when the tenant has no such node, 503 `profile-unavailable` when the profile service cannot say; a cursor of another list is 422 `pagination-cursor-invalid` |

The four tracking routes are in the public API too (from 0.2.0): `GET /v1/obligations/{obligation_id}`,
`POST /v1/obligations/{obligation_id}/status`, `PUT /v1/obligations/{obligation_id}/assignee` and
`POST /v1/obligations/{obligation_id}/comments` run the same handlers. Every change requires an
`Idempotency-Key` header (8 to 128 printable characters; 428 `idempotency-key-required` without
one): a retry with the same key and body gets the first answer back for 24 hours with
`Idempotent-Replayed: true`, the same key with another body is 422 `idempotency-key-reused`, and a
retry while the first runs is 409. Keys are kept per tenant in `idempotency_key`, each in its own
short transaction (`py_common.idempotency`).

Who calls and for which tenant comes from `py_common.auth` by `CW_AUTH_MODE` (`api/deps.py`):

- `header` (the default): the `x-tenant-id` header names the tenant, and no token is read.
- `dual`: a bearer token is verified when the request carries one, and then counts as in
  `token` mode; without one the header counts, as in `header` mode.
- `token`: a bearer token is required (401 `auth-token-required`). A user's token names the
  tenant, and the user needs one of the tenant member roles (owner, staff, ca_admin, ca_staff,
  compliance_lead); an `x-tenant-id` naming another tenant is a 403 `auth-tenant-mismatch`. A
  service (the qa service reading the obligations a question is about) names the tenant in
  `x-tenant-id` and needs the tenant:act scope; it may read, never change an obligation. Anyone
  else is a 403 `auth-forbidden`.

The changes record who made them: the user a token names (`closed_by`, the change's `actor`, the
comment's `author_id`) labelled with their roles in the audit row and the comment, or nobody,
labelled `system:obligation`, when no token named the caller. Outside `header` mode the service
calls identity (an assignee's membership) and profile (whether a business is the tenant's, at
`CW_PROFILE_URL`) with its own token: `CW_SERVICE_CLIENT_ID` (obligation) and
`CW_SERVICE_CLIENT_SECRET`, a client with the tenant:act scope (`identity_dev_clients.toml` makes
it in local and test runs), or the token the one deployable mints in its process.

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
  api/             # router.py (the read and tracking routes, and the public API's), schemas.py, deps.py (caller and tenant, wiring)
  application/     # materialise.py, changes.py, decisions.py, guard.py, rule_events.py, window.py, reminders.py, queries.py, tracking.py
  domain/          # model.py (Obligation, DueWindow), events.py, errors.py, history.py, comments.py, reminders.py, rule_versions.py, ports.py, repository.py (protocols)
  infrastructure/  # models.py, repository.py (Postgres unit of work with the outbox and the audit), memory.py, rulebook_client.py, identity_client.py, profile_client.py, metrics.py
  wiring.py        # what the api layer gets from the composition root
  main.py          # composition root: wire(settings), build_app(settings), problem statuses
  worker.py        # the worker's composition root: components(settings), both handlers, the sweep and window jobs
  sweep.py         # obligation-sweep --once: the reminder sweep and the rolling window, once
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
make run SERVICE=obligation           # http://localhost:8005/health, /ready, /v1/obligation/obligations[/{id}]
make worker SERVICE=obligation        # both consumers (and the sweep and the window when enabled)
uv run --package compliancewatch-obligation obligation-sweep --once --now 2026-11-15T10:00:00+05:30 --tenant <id>
make test                         # unit + contract tests with the coverage gate
docker build -f services/obligation/Dockerfile -t compliancewatch-obligation .
```

`CW_OBLIGATION_STORE=memory|postgres` picks the store (memory for tests and demos; the readiness check pings whichever is wired). Package `obligation`, dev port 8005, Postgres schema `obligation`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

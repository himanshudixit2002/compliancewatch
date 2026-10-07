# applicability-engine service

Part of the ComplianceWatch monorepo. **Deterministic evaluation of one rule version against one business, stored append-only with its event; recompute on profile.updated (behind the flag `applicability.recompute`), the business directory, the review queue, the rule.published fan-out over the directory as a Temporal workflow with its hold and controls (behind the flag `applicability.fanout`), the impact of a change on a tenant (public API) and an admin's dry run of a version over the directory; no LLM judge yet.**
Design reference: Project Foundation guide, sections 7, 8, 11 and 14.

- **Owns:** ApplicabilityDecisions: coarse filter by regulator and attribute index, per-business predicate evaluation, LLM-judged free-text predicates with confidence, Temporal fan-out in batches of 1,000
- **Owning team:** Core Product (deterministic path and fan-out); AI Platform owns the LLM evaluator (guide section 14)
- **Consumes:** profile.updated (the business and the registrations under it; group `applicability-engine.profiles`); rule.published and rule.withdrawn (the fan-out; group `applicability-engine.rules`); tenant.deletion.requested (group `applicability-engine.erasure`); profile and rulebook read APIs; LLM gateway API (not yet)
- **Emits / publishes:** applicability.decided and tenant.data.erased

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
- `application/recompute.py`: `ApplyProfileUpdate`, what the worker does with one
  profile.updated, in two phases so no HTTP call is ever made inside a database transaction.
  `plan` reads over HTTP only: the changed node's snapshot (its level and lineage) and, for a
  legal entity, the registrations under it (`GET /v1/businesses/{id}`); with recompute on, each
  node's snapshot for the current financial year in India and the rule versions in force for the
  node's level (`rules_in_force(as_of, level)`), and evaluates every pair. `apply` writes in one
  unit of work of the tenant: the directory entries, then each decision unless it is already
  stored. The decision's id derives from the event (`trigger_ref` `profile.updated:<event id>`),
  the business and the rule version, and the store keeps one decision per (trigger_ref,
  business, rule version), so a replayed event inserts nothing. A stored decision publishes
  `applicability.decided` when its result is `applies` (the obligation service then makes any
  period of its window still missing, idempotently) or when its result or its need for review
  differs from the previous decision of the business and rule version (none before counts as
  different); an unchanged not_applicable or unsure decision is stored without an event. With
  recompute off only the directory is kept. The versions are the ones in force today in India
  and, with `CW_APPLICABILITY_ENGINE_RECOMPUTE_LOOKAHEAD_DAYS` (92), the ones that take effect
  within that many days: a version published to take effect later already makes the obligations
  of the periods of the obligation service's window it governs, so its decision has to follow
  the profile before it takes effect. With `CW_APPLICABILITY_ENGINE_SUPERSEDED_LOOKBACK_DAYS`
  (400, enough for an annual return; 0 turns it off) they also include the versions superseded
  within that many days (`rules_superseded_since`: the rulebook's
  `GET /v1/rulebook/rule-versions?ended_on_or_after=&status=superseded`, never a withdrawn
  version, which governs nothing) that still govern a duty due today or later
  (`RuleVersionSpec.still_governs`). A version governs the periods whose last day it is in force
  on, so a monthly return's version superseded from 1 October still governs September, due 20
  October: a business onboarded on 5 October is decided for it, and the obligation service makes
  September of that decision and refuses October and November, the newer version's; onboarded on
  25 October, nothing of it is due and it is left out. The kernel judges it
  (`Recurrence.periods_governed`, the rule the obligation service makes periods by); a one-off
  belongs to the version in force on its due day, so a superseded one is never decided. These
  decisions have the usual trigger and ids, so a replayed event stores nothing. Until the
  rulebook's daily sweep moves a version its replacement took over that day (00:05 IST), the
  version is in neither listing. The profile service lists no locations, so a change on an
  entity or a registration does not reach the locations under it; a change on a location
  recomputes the location.
- `domain/review.py`, `application/review.py`: the review queue. A decision opens an item when
  it needs review because of a free-text predicate nobody judged (`free_text`) or a judgement
  below the review threshold (`low_confidence`). Unsure only because the profile has not set an
  attribute opens none (the owner answers the question, and the next profile.updated decides
  again), nor does an attribute or comparison the ontology refuses, a fault of the rule. At most
  one item of a business and rule version is open; while open it follows the latest decision of
  its pair, and a later decision that needs no review settles it (`dismiss`, no person, a note
  naming the decision). `ResolveReviewItem` settles an open item for a reviewer: `applies` or
  `not_applicable` appends a decision with trigger `review` (made from the decision under review,
  confidence 1, `trigger_ref` `review:<item id>`) and publishes its `applicability.decided`;
  `dismiss` appends nothing. Every stored decision, the manual ones included, keeps the queue in
  step in its own transaction (`track_review`). A person's resolution is not carried over: a
  later profile change that leaves the rule unsure on its free-text predicate opens a new item.
- `domain/fanout.py`, `application/fanout*.py`, `application/rule_events.py`,
  `workflows/fan_out.py`: the fan-out of a published version over the business directory
  (ADR-004 and its 2026-10-05 addendum; [the runbook](../../docs/runbooks/fan-out-control.md)).
  - `RuleEvents` is what the consumer of group `applicability-engine.rules` does, in the same
    two phases as the recompute. On rule.published it drops the rulebook client's cached listings,
    reads the version (status, rule key, level, schedule) and, with the flag `applicability.fanout`
    on (`CW_APPLICABILITY_FANOUT_ENABLED`, off by default), starts its workflow, all with no
    transaction open; then it records the run in `fanout_run` (`running`, or `disabled` with the
    flag off, which never runs). A version the rulebook no longer has or withdrew fans out nowhere,
    nor does a superseded one unless it still governs a duty due today: an event read after a
    newer version took over still fans the older one out to the businesses that owe its last
    periods. A newer version's fan-out decides the newer version alone, since the businesses keep
    their decisions of the one it supersedes. On rule.withdrawn it drops the cache and cancels the
    version's run that has not finished, audited as the system.
  - `FanOutWorkflow` runs `fanout_flow.drive` on the task queue `applicability`, workflow id
    `applicability-fan-out-<rule version id>`, a duplicate start refused (`REJECT_DUPLICATE`).
    `EvaluateBatch` decides 1,000 directory entries of the version's level per batch, one tenant
    group at a time, while the version is published, or superseded and still governing a duty due
    today (a run its supersession overtook carries on for the businesses it has not reached; one
    that owes nothing more fails as not published): the profiles over HTTP with no transaction
    open, then the group's decisions
    (trigger `rule_published`, `trigger_ref` `rule.published:<event id>`) with their events by the
    recompute's emit rule and `track_review`, in one unit of work of the tenant. It counts flips
    against the latest decision of the versions the event's `supersedes` names. After 100
    batches the workflow continues as new with its cursor.
  - At every batch boundary it reads the global hold (`fanout_hold`) and its row: held while the
    hold is set, waiting while paused, ended when cancelled. Once 200 businesses were compared, a
    flip rate above 2% pauses it, audited as `system:applicability-engine`. Signals `pause`,
    `resume` and `cancel` wake it, and the query `progress` says where it stands.
  - The activities (`fanout_activities.py`) are idempotent: begin inserts the run once, the
    counters and statuses are written whole, a status already reached is not moved or audited
    again. The database steps retry until it answers; a batch for about 40 minutes, then the run
    fails with `last_error`.
  - `PauseFanOut`, `ResumeFanOut`, `CancelFanOut`, `SetHold` and `ReleaseHold` (`fanout.py`)
    change the row and write the audit entry (`applicability.fanout.pause`, `.resume`,
    `.cancel`, `.hold`, `.release`, of no tenant, the actor from the request's principal) in one
    unit of work, then signal the workflow (`infrastructure/temporal.py`). Pausing, cancelling and
    holding need a reason of at least ten characters.
  - `applicability_engine.testing.LocalFanOuts` runs the same loop and activities on a thread
    for tests and demos without Temporal.
- `domain/impact.py`, `application/impact.py`: the impact of a change on one tenant,
  `ReadChangeImpact`. It reads the engine's own tables only, with nothing over HTTP: the tenant's
  latest decision of the version per business (decided_at, then id; a decision of any trigger),
  each placed under the legal entity at the top of its lineage as the business directory records
  it (the business itself, with no level, when the directory does not list it), a page of
  entities at a time, optionally of one result; the counts of those latest decisions by result;
  and the version's `fanout_run`, in a second short transaction of no tenant. The Postgres store
  reads `DISTINCT ON (business_id)` from a backward scan of `ix_applicability_decision_impact`,
  under the unit's row-level security, joining the directory on the decision's tenant.
- `application/dry_run.py`: `DryRun`, what a rule version in any status, or a specification no
  version holds, would decide for the businesses the directory lists at the level (the version's
  own, or the scope's with a specification), of one tenant when the scope names one, for the
  current financial year in India, as a fan-out evaluates it. The directory entries in scope are
  counted first, and more than `CW_APPLICABILITY_DRY_RUN_MAX` (2,000) is refused (422
  `applicability-dry-run-too-large`) before anything is read; then each profile snapshot is read
  over HTTP with no transaction open and evaluated in the process. It stores no decision, opens
  no review item, starts nothing and publishes no event; its one write is the audit entry
  `applicability.dry_run`, of no tenant, with the actor, the subject (`rule_version` and the
  version id, or `specification` and the first 32 hex digits of the SHA-256 of its mapping) and
  in `after` the scope and the counts. The report counts the businesses by result and, for each
  attribute that decided a result (`domain.evaluation.deciding_attributes`: the predicates that
  made the result, those that ruled it out, made it apply or left it unsure), by result again,
  and keeps up to `sample_size` (0 to 50, 10) decisions, a result at a time.
- `application/export.py`: `ExportTenantData`, the engine's part of a tenant's data export
  (`GET /v1/applicability-engine/data-export`, which identity calls on a download with a service
  token holding data:export only, bound to the tenant and addressed to `applicability-engine`, so
  it is refused for another tenant or at another service; an owner or a CA admin of the tenant
  may call it too).
  Section `decisions` holds every decision of the tenant, superseded and reviewers' ones included,
  with each predicate's outcome; section `review_items` the review queue's items, open and
  resolved. Both are read in one unit of work of the tenant, 500 rows a page (decided_at or
  opened_at, then id), oldest first; each is present even when empty. The fan-out runs, the hold
  and the business directory, which the engine keeps across tenants, are left out, and no audit
  entry is written (identity writes `data_request.exported`).
- `infrastructure/`: the HTTP clients (`profile_client.py`, `rulebook_client.py`; a 404 is
  `None`, anything else unexpected is `DependencyUnavailableError`, 503); the rulebook's listings,
  in force on a day (paged by rule key) and superseded since a day (paged by rule key and version,
  since a rule can have several), are each cached per day for
  `CW_APPLICABILITY_ENGINE_RULES_CACHE_SECONDS` (60; 0 turns it off), and dropped at once on every
  rule event (`forget_in_force`); every version read carries its schedule (effective dates,
  recurrence, the template's `due_in_days`). The Postgres
  unit of work sets `app.tenant_id` per transaction and writes events to the outbox and audit
  entries to `audit.event` on the same connection; `PostgresUnitOfWorkFactory.on_connection`
  makes units inside the consumer's transaction, and `PostgresBusinessDirectory` reads the
  directory across tenants (for the fan-out). `PostgresFanOutUnitOfWorkFactory` opens units of no
  tenant over `fanout_run`, `fanout_hold` and the audit log. `temporal.py` starts and signals the
  workflows. `memory.py` is the in-memory twin, with the same rules.
  `applicability_engine.testing` has in-memory readers and builders.
- `worker.py`: `python -m applicability_engine.worker` (`make worker SERVICE=applicability-engine`,
  needs `CW_APPLICABILITY_ENGINE_STORE=postgres`), and the combined worker (`cw-mvp worker`): the
  two consumers and the Temporal worker of the queue `applicability`. The consumer group
  `applicability-engine.rules` reads rule.published and rule.withdrawn (above); the consumer group
  `applicability-engine.profiles` reads profile.updated through
  `py_common.outbox.read_then_write`: the reads run with no transaction open, then the
  directory, the decisions with their outbox rows, the review items and the `processed_event`
  row commit together. What it cannot read or handle goes to
  `profile.updated.applicability-engine.profiles.dlq` after the consumer's retries. Its
  profile and rulebook calls carry the worker's service token (tenant:act) once
  `CW_SERVICE_CLIENT_SECRET` is set. The outbox relay runs on its own (`make relay
  SERVICE=applicability-engine`) or in the combined worker.
- `migrations/versions/20261001_0001_applicability_decisions.py`: `applicability_decision` with
  forced row-level security and an append-only trigger (DELETE only under `app.erasure=on`),
  the outbox and `idempotency_key`.
- `migrations/versions/20261004_0002_recompute_and_review.py`: `processed_event`;
  `business_directory`, a routing directory in `infra/scripts/migration_lint.toml` (forced
  row-level security, every write under the tenant policy, `business_directory_read` lets any
  session read the ids and levels); `review_item` with the tenant policy, the partial unique
  index `uq_review_item_open` and foreign keys to the decisions that cascade on a tenant's
  erasure; `trigger_ref` on the decisions with `uq_applicability_decision_trigger_ref`, and the
  trigger `review`. Expand-only; the downgrade deletes no decision (the narrowed trigger CHECK is
  `NOT VALID`). `make product-role` grants the new tables to `cw_app` like every other.

- `migrations/versions/20261005_0003_fan_out.py`: `fanout_run` (one row per published version:
  rule key, level, status, the counters, the trigger event, when it started, changed and finished,
  why and by whom its status last changed, its last error) and `fanout_hold` (one row while the
  global hold is set). Rule-level, of no tenant and without row-level security, so both are exempt
  in `infra/scripts/migration_lint.toml`; `make product-role` grants them to `cw_app` like every
  table of the schema.
- `migrations/versions/20261006_0004_impact_index.py`: `ix_applicability_decision_impact`
  (tenant_id, rule_version_id, business_id, decided_at, id) on the decisions, for the impact of a
  change. Expand-only.

Routes, for the request's tenant (`api/deps.py`):

- `POST /v1/applicability-engine/businesses/{business_id}/decisions` with `rule_version_id` and
  an optional `fy`: evaluate and store; requires `Idempotency-Key`. 404 for an unknown rule
  version or business, 409 for a version that is not published, 503 when a dependency fails.
- `GET /v1/applicability-engine/businesses/{business_id}/decisions`: newest first, `limit` and
  `cursor` (py_common.pagination), optional `rule_version_id`.
- `GET /v1/applicability-engine/decisions/{decision_id}`: one decision with every predicate's
  outcome, confidence and reason.
- `GET /v1/changes/{rule_version_id}/impact?result=&limit=&cursor=`: in the public API (tag
  `public`, `x-roles` the tenant member roles), beside the rulebook's `GET /v1/changes`. The
  tenant's clients (`items`, by entity id, keyset paged a client at a time), each with its
  businesses and their latest decision of the version: result, confidence, `needs_review`,
  `decided_at`, the trigger and every predicate's outcome in words (`evaluated`); `result=applies`
  keeps the affected ones, a CA firm's affected-clients list. `counts` covers every business of
  the tenant with a decision of the version, and `fan_out` gives the status and counters of the
  version's run (null when it had none). A version the engine never decided reads as one with no
  clients.

The review queue, for the regulatory team, acts for the tenant `x-tenant-id` names (401
`applicability-tenant-required` without it):

- `GET /v1/applicability-engine/review-items?status=open|resolved&limit=&cursor=`: the tenant's
  items, oldest first (opened_at, then id), keyset paged, each with the decision under review
  and every predicate's outcome.
- `POST /v1/applicability-engine/review-items/{item_id}/resolve` with `resolution` (`applies`,
  `not_applicable` or `dismiss`), a `note` and `resolved_by`: 404
  `applicability-review-item-not-found`, 409 `applicability-review-item-resolved`.

Who may call them, by `CW_AUTH_MODE` (`api/deps.py`): a user a token names needs a regulatory
role (analyst, reviewer or admin) to read and a reviewer or admin to resolve, and is recorded
as the one who resolved, whatever the body says. Those roles exist only in the internal tenant,
whose people review every tenant's decisions, so on these two routes alone the header names the
tenant reviewed rather than the user's own; tenant members and services are a 403. In `header`
mode the anonymous caller passes and the body's `resolved_by` is recorded; in `dual` mode a
resolution without a token is a 401. The one deployable classes both routes `admin`: the public
listener serves them in token mode only (`composition/mvp`). Every resolution writes an audit
entry, `applicability.review.resolve`, in its unit of work (`audit.event` through
`py_common.audit`; `MemoryStore.audit` in memory): the reviewer a token names as the actor, else
`system:applicability-engine`, the note as the reason, the item's state before and after, and the
request's correlation id. An item a later decision settles by itself is not audited: no person
acted, and the item names the decision that settled it.

The fan-outs, for the regulatory team; they run over every tenant, so no route names one
(`api/deps.py`: `FanOutReader`, `FanOutAdmin`):

- `GET /v1/applicability-engine/fan-outs?limit=&cursor=`: every run, newest first (started_at,
  then rule version id), keyset paged; `GET /v1/applicability-engine/fan-outs/{rule_version_id}`:
  one run (404 `applicability-fan-out-not-found`).
- `POST /v1/applicability-engine/fan-outs/{rule_version_id}/pause` with a `reason` (running or
  held), `.../resume` (paused; an optional `reason`) and `.../cancel` with a `reason` (not
  finished): 409 `applicability-fan-out-state` otherwise, 422 for a reason under ten characters.
- `GET /v1/applicability-engine/fan-out-hold` and `PUT` with `held` and a `reason` (required to
  set it): releasing wakes every run the hold stopped.

Who may call them, by `CW_AUTH_MODE`: a user a token names needs a regulatory role (analyst,
reviewer or admin) to read and the admin role to control; tenant members and services are a 403.
In `header` mode the anonymous caller passes, audited as `system:applicability-engine`; in `dual`
mode a control without a token is a 401. The one deployable classes every fan-out route `admin`.

The dry run, for an admin, names no tenant unless its scope does:

- `POST /v1/applicability-engine/dry-runs` with `rule_version_id` (a version in any status) or
  `specification` (the kernel's predicate tree mapping), exactly one, and a `scope`: `level`
  (required with a specification; with a version, its own, and another is a 422), `tenant_id`
  and `sample_size`. 200 with the report: `businesses_total` (the directory entries in scope),
  `evaluated`, `skipped` (no profile any more), `counts`, `needs_review`, `by_attribute`,
  `samples`, `as_of_fy`, `max_businesses`; 404 for a version the rulebook lacks, 422 for a
  malformed specification or a scope over `CW_APPLICABILITY_DRY_RUN_MAX`, 503 when the rulebook
  or the profile service cannot be read. No Idempotency-Key: it creates nothing, and a repeat
  writes another audit entry.

It takes the fan-out controls' guard (`deps.DryRunAdmin`): an admin a token names, the anonymous
caller in `header` mode only (audited as `system:applicability-engine`), and a 401 without a token
in `dual` mode; it reads every tenant's profiles. The one deployable classes it `admin` and
counts it among the routes that call other services while they serve (`loopback_routes`).

Not built yet: the LLM evaluator for free-text predicates, the golden set, and the coarse filter
over indexed profile attributes that lets a fan-out skip businesses a version cannot apply to.

## Erasure

The worker's consumer of tenant.deletion.requested, group `applicability-engine.erasure`, only
logs `erasure.off` while the flag `identity.tenant_erasure` (`CW_TENANT_ERASURE_ENABLED`, per tenant with `CW_TENANT_ERASURE_TENANTS`; off by default) is off for the tenant. On, under the tenant's setting and
`app.erasure` (the only way past the decisions' append-only guard), it deletes the tenant's
`review_item`, `applicability_decision` and `business_directory` rows, its idempotency keys and
its published events, and answers tenant.data.erased (service applicability-engine) with the row
counts and a `tenant.erased` audit row, in the transaction that marks the event processed
(`infrastructure.erasure`). It keeps `fanout_run` and `fanout_hold`, rule-level counters with no
tenant. A profile.updated or rule event still in flight can write a directory entry or a decision
after the erasure; the staging drill checks for it and `identity-admin erasure resend` erases
again.

## Layout

```
src/applicability_engine/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models, repositories, Kafka, adapters
  main.py          # composition root: create_app(...) from py-common
  worker.py        # the worker's composition root: components(settings), the profile.updated handler
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
make worker SERVICE=applicability-engine        # both consumers and the fan-out's Temporal worker (CW_APPLICABILITY_RECOMPUTE_ENABLED, CW_APPLICABILITY_FANOUT_ENABLED)
make test                         # unit + contract tests with the coverage gate
docker build -f services/applicability-engine/Dockerfile -t compliancewatch-applicability-engine .
```

Package `applicability_engine`, dev port 8004, Postgres schema `applicability`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

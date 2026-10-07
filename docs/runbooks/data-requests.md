# Data requests (DataRequestOverdue)

A tenant asks for a copy of its data (an export) or for its deletion through
`POST /v1/identity/data-requests`: its owner or CA admin for their own tenant, or the regulatory
team's admin for a tenant that asked support, with a reason. Each request is due 30 days after it
was made (the data map, `docs/legal/data-map.md`, until counsel confirms the period). The
erasure that answers a deletion is below ("Deletion: the erasure cascade").

An export is answered as soon as it is made: the request is `in_progress`, and the bundle is
assembled whenever the owner downloads it (`GET /v1/identity/data-requests/{id}/export`) and never
stored: identity's own data of the tenant, then the part each service of
`CW_IDENTITY_EXPORT_SOURCES` answers on `GET /v1/<service>/data-export` (profile, the
applicability engine, obligation and notification). Identity calls each service with a token it
mints for that call: scope `data:export` only, bound to the tenant (`tid`) and addressed to that
service (`aud` is `compliancewatch:<service>`), living two minutes; each service refuses it for
another tenant or if it is addressed elsewhere (403). The services are asked four at a time, 20
seconds each at most and all within 45 seconds (`CW_IDENTITY_EXPORT_CONCURRENCY`,
`CW_IDENTITY_EXPORT_TIMEOUT_SECONDS`, `CW_IDENTITY_EXPORT_DEADLINE_SECONDS`). A service that does
not answer in time is named in the bundle (`services_pending`, and its entry says `status:
unavailable` with the reason), and the request stays `in_progress` with that service pending; the
download itself still answers 200. The request completes from the first download in which every
service has answered (answers of several downloads add up). Each request writes
`data_request.created`, and each download `data_request.exported` naming the services that
answered and those still pending, to the tenant's audit trail.

An export the owner never downloads is not overdue: the operator has answered it, and only the
tenant can complete it. Thirty days after it was made it expires quietly: it no longer counts as
open, nothing pages, and the owner may still download it or ask again. An export still
`received`, never answered at all, counts as overdue past its deadline, and so does a deletion
that is not `completed`, whatever its status: only the operator can make the services erase.

- `DataRequestOverdue` (page, Identity and Partner): at least one request, of any tenant, has been
  past its deadline and still owed (an export never answered, a deletion not completed), for an
  hour.

Identity reports `identity_data_requests_open{kind}` (every tenant's requests neither completed
nor expired, zero when none) and `identity_data_requests_overdue` (those past their deadline and
still owed) when `CW_OTEL_ENDPOINT` is set, from a reading it takes at most once a minute. The reading goes
through `identity.data_requests_open()`, a `SECURITY DEFINER` function owned by the NOLOGIN role
`cw_identity_directory` that answers counts per kind and no row: identity's own role sees one
tenant's requests at a time under row-level security. A failed reading logs
`data_request_metrics.read_failed` and reports nothing, so the alert sees a gap rather than a
false zero.

## Deletion: the erasure cascade

A deletion request, in one transaction at identity: the request (`received`, due in 30 days),
the tenant turned `deletion_requested`, `tenant.deletion.requested` in identity's outbox (its
event id kept on the request: the event every service checks) and a `data_request.created` audit
row. From then on nobody signs in to the tenant (the session exchange answers 403
`identity-tenant-deleting`), its tokens open no identity route but the reads of its data requests
and its audit trail, and it can ask for nothing more. The web has the plain reason ready as the
message key `signIn.refusal.tenantDeleting`, but nothing shows it yet: the web has no session
exchange proxy, and the key is wired when that lands (W3). Only identity's routes refuse the
tenant at once: the other services take a token issued before the request until it expires (ten
minutes by default), and answer 410 `tenant-erased` once each has erased the tenant. The internal
tenant is never erased (422 `identity-tenant-not-erasable`).

Six consumers answer the event, each in its group `<service>.erasure` in the worker
(`cw-mvp worker`, or `make worker SERVICE=<service>`), each in one transaction with its
`processed_event` row, with `app.tenant_id` and `app.erasure` set (`py_common.erasure`). Each
first checks the event, with no transaction open: identity against its own records, every other
service with `GET /v1/identity/erasures/{tenant_id}` (internal, scope `erasure:verify`, 5 s). It
erases only when the tenant asked for its deletion (or identity erased it already), is not the
internal tenant, and the event is the one identity last sent for the tenant's open deletion
request. Any other event erases nothing, not even at the identity provider: the consumer writes a
`tenant.erasure_refused` audit row with the reason and dead-letters the event at once. Identity
unreachable is retried, then dead-lettered; nothing is erased.

| Service | Erases | Keeps |
| --- | --- | --- |
| identity | the users' accounts at the identity provider (first, with no transaction open; an account already gone counts), `app_user` (every session with it), `user_subject`, `idempotency_key`; pseudonymises `consent_record` (subject `erased:` + 32 hex of HMAC-SHA256 keyed with `CW_IDENTITY_ERASURE_PEPPER` over tenant\|subject, evidence emptied, `recorded_by` nulled) and the billing customer's email (the same pseudonym) and name (emptied); empties the checkout links of the subscriptions and starts; empties the tenant's name and marks it `erased` | the pseudonymised consents and billing customer, the subscriptions, starts and masked webhooks (tax records), the data request, the erased tenant |
| profile | `profile_version`, `profile_attribute`, `review_task`, `profile_node`, `idempotency_key` | nothing of the tenant |
| obligation | `obligation_change`, `obligation_comment` (append-only, under `app.erasure`), `obligation_reminder`, `obligation`, `obligation_decision`, its `obligation_tenant` row, `idempotency_key` | `rule_version_ref` (rule-level cache) |
| notification | `work_index` and `notification` (receipts with them), `recipient_address`, `recipient_business`, `recipient`, its `address_directory` rows, `idempotency_key`; the opt-in `channel_preference` of an address no other tenant holds | opt-outs (the record that the person asked to stop, which must outlive the account), an opt-in another tenant still holds (in its directory, or set by its user), each with this tenant's `set_for_tenant_id` nulled; `suppression` |
| applicability-engine | `review_item`, `applicability_decision` (append-only, under `app.erasure`), its `business_directory` rows, `idempotency_key` | `fanout_run`, `fanout_hold` (rule-level) |
| rulebook | nothing: it holds regulatory data of no tenant | the documents, rules, candidates and their review |

Every service also prunes the tenant's published or dead `outbox_event` rows (pending ones go out
with the relay; nothing prunes the outbox on its own, see `docs/runbooks/outbox-relay.md`), writes
its erased marker (`erased_tenant`: the tenant, when, the event's id), a `tenant.erased` audit row
and `tenant.data.erased` with the row counts per table and the tables it kept, each with the
reason. From its marker on, the service's routes answer the tenant 410 `tenant-erased`, whoever
asks, and its consumers mark the tenant's events processed (outcome `erased_tenant`) and write
nothing: a consumer that checked the marker before the erasure started holds the erasure's lock
until it commits, so what it wrote goes with the erasure.

Identity's group `identity.erasure-records` records each answer to the event it sent last (an
answer to another event changes nothing): the first turns the request `in_progress`. Once every
service of `CW_IDENTITY_ERASURE_SERVICES` (by default identity, profile, obligation, notification,
applicability-engine, rulebook) has answered, identity writes the second pass, the same request
as a new event, to its outbox, held back `CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS` (900: longer
than an access token lives), with a `data_request.second_pass_scheduled` audit row; the relay
sends it then. Every service checks and answers it like the first, and the request completes,
with `data_request.completed`, once they all have: a write that slipped past the first pass (a
request on a route that checked the marker just before the erasure, a fan-out batch that read the
directory before it) goes in the second. `GET /v1/identity/data-requests/{id}` shows the pass
(`erasure_pass`), when the second goes out (`second_pass_at`) and the services still pending. The
audit log is never erased: its rows are masked and kept seven years. The llm-gateway's cost ledger
keeps the tenant id only (13 months) and has no handler; qa holds no tenant data.

### The flag

`identity.tenant_erasure` (`CW_TENANT_ERASURE_ENABLED`, per tenant with
`CW_TENANT_ERASURE_TENANTS`; owner identity-partner; off by default) is read by every erasure
consumer, through one switch per worker process. With it off, the request is still recorded, the
tenant still shut and the event still emitted, but every consumer only logs `erasure.off` and
marks the event processed: nothing is erased, the request stays `received`, and 30 days later it
is overdue and pages. That is meant: a request is never silently done. To answer it once the flag
is on for the tenant, send it again:

```bash
CW_DATABASE_URL=... identity-admin erasure resend --tenant <tenant id> --reason "flag turned on"
```

`resend` writes a new `tenant.deletion.requested` for the tenant's open deletion request, makes it
the event the services check, and writes a `data_request.resent` audit row. Every service's
erasure is idempotent, so one that answered already erases nothing more and answers again. An
older event of the request still in flight is refused from then on (dead-lettered, with a
`tenant.erasure_refused` row): expected, and nothing to do. A completed request is not sent
again (404 `identity-deletion-request-not-found`): every service would refuse it. The flag stays
off everywhere until counsel has reviewed the data map, `CW_IDENTITY_ERASURE_PEPPER` is set, the
consumers' clients hold `erasure:verify`, and a staging drill has erased a synthetic tenant
(`infra/deploy/README.md`); never run an erasure against a shared dev database.

### When a deletion is pending

1. `GET /v1/identity/data-requests/{id}` (as the owner while its token lasts, or the directory
   query of step 1 below) names the services still pending and the pass.
2. Is the flag on for the tenant? Each consumer logs `erasure.off` with the tenant while it is
   off.
3. Is the worker consuming? `/loops` on the worker's health port lists
   `<service>/consumer:<service>.erasure`; is the relay of identity's schema publishing? In the
   second pass, has `second_pass_at` passed? Until then the event waits in identity's outbox.
4. Did a handler dead-letter? Look at `tenant.deletion.requested.<service>.erasure.dlq` (and
   `tenant.data.erased.identity.erasure-records.dlq`); the consumer logs
   `consumer.dead_lettered` with the error, or `erasure.refused` with the reason and a
   `tenant.erasure_refused` audit row. A refusal of an event identity did not send, or of an
   older event after a resend, is right: leave it. A refusal of the current event means the
   service and identity disagree: compare `GET /v1/identity/erasures/{tenant_id}` with the
   event. `IdentityUnreachableError` (identity down, or 403 without `erasure:verify`) and
   `ProviderUnavailableError` (the identity provider) are retried with the next delivery. Fix the
   cause, then `make replay` the message (it is checked again) or `identity-admin erasure
   resend`.
5. A user whose account lives at another provider than the one configured is deleted from the
   store but not at that provider. Identity's `tenant.erased` audit row lists each one under
   `other_provider_accounts` (user id, provider and the provider's subject, masked where it reads
   as a phone number or an email address), and the log line `identity.provider_accounts_deleted`
   names them too: delete each account there by hand and note it in the ticket.
6. Outside the databases: remove the tenant's lines from `CW_PROFILE_EVAL_CASES_PATH` where it is
   set; the Kafka topics and dead-letter topics keep the event (and its free-text reason) for 7
   and 30 days, and the engine's Temporal histories for the namespace's retention; backups age
   out with their retention, and a restore must run the erasure again (`resend`, while the
   request is open) before the tenant's data is served.
7. After it completes, nothing of the tenant comes back: every service's routes answer 410 and
   its consumers drop the tenant's events by its marker. If a row of the tenant turns up anyway,
   it is a bug: the services' integration tests read every table with a tenant column from the
   catalog and fail on one their eraser neither erases nor retains.

## When it fires

1. See what is overdue, as `cw_identity` or `cw_app` (the roles that may run the function):

   ```sql
   SELECT * FROM identity.data_requests_open();
   ```

   To find which tenant: forced row-level security holds the owner too, so read the rows as the
   directory role (the owner may act as it, since it is a member WITH SET; a superuser on the
   dev stack may too), in one transaction:

   ```sql
   BEGIN;
   SET LOCAL ROLE cw_identity_directory;
   SELECT id, tenant_id, kind, source, requested_at, deadline_at, status, services_done
     FROM identity.data_request
    WHERE deadline_at < now()
      AND (status = 'received' OR kind = 'deletion' AND status <> 'completed')
    ORDER BY deadline_at;
   ROLLBACK;
   ```

2. A `received` export was never answered: answer it, and note it in the support ticket. A
   deletion that is not completed: follow "When a deletion is pending" above. A support request for a tenant the team cannot
   reach (no active owner) is escalated to the Identity and Partner lead.
3. An export that is `in_progress` and the tenant says it is missing data names the services
   still pending (`GET /v1/identity/data-requests/{id}` answers `services_pending`); this does not
   page. For each one:
   - is the service up, and is its `GET /v1/<service>/data-export` answering for the tenant?
     Identity logs `identity.export_source_failed` with the service and the reason (`answered
     503`, `unreachable (ConnectError)`, `answered the export of another tenant`), never the body;
   - is `CW_IDENTITY_EXPORT_SOURCES` right for this deployment (the combined product points every
     source at its internal listener by itself; separate processes need the addresses)?
   - in token mode, does the service trust identity's keys (`CW_AUTH_JWKS_URL`)? A 401 from a
     source is a key problem; a 403 means the token was refused: for another tenant, addressed
     to another service (the name in `CW_IDENTITY_EXPORT_SOURCES` must be the service's own), or
     without `data:export`.

   Once the service answers, the next download completes the request; ask the owner to download
   again.
4. Never mark a request completed by hand: the deadline is what the tenant was promised, and the
   audit trail must show the export that met it.

## After an incident

Write down which tenant, how late, and why, in the support ticket; a request past its deadline
may have to be reported (docs/legal, counsel to confirm). If a source keeps failing for one
tenant, look for data that service cannot serialise (its logs name the error), and fix it there.

## The directory role

`infra/dev/postgres/roles.sql` makes `cw_identity_directory` (NOLOGIN, no attribute), its read
policy `data_request_directory` (FOR SELECT, `USING (true)`, for that role only) and the function,
once identity's migration 0010 has made `data_request`; `make migrate` and `make db-roles` run it,
and so does a deployment's role step (`infra/deploy/README.md`). Only `cw_identity` and `cw_app`
may run the function: the role itself takes EXECUTE from PUBLIC and grants it, as the function's
owner, since an owner that is not a superuser holds no grant option on it. A deployment's owner
that is not a superuser is made a member of the role with `INHERIT FALSE, SET TRUE`: it does not
inherit the role's reads, but it may `SET ROLE` to it and read every tenant's requests, as step 1
does. That is acceptable: the owner owns identity's tables and could switch their row-level
security off anyway. If the gauges report nothing and the logs say the function does not exist,
run the role step again.

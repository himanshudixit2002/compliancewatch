# identity service

Part of the ComplianceWatch monorepo. **Tenants, users and roles (row-level security, events through the outbox), sign-in through an identity provider (a fake one locally, Supabase Auth in the MVP, ADR-014), the access tokens every service verifies (ES256, published as a JWKS), service tokens for service clients, consent records (append-only) with their API, channel consents for WhatsApp numbers no tenant owns yet, and billing behind a flag: the `BillingProvider` protocol, an in-memory provider and a Razorpay skeleton, the billing ledger in Postgres, the entitlements a tenant's plan gives and the plan limits behind `identity.plan_limits`.**
Design reference: Project Foundation guide, sections 7, 14 and 16.

- **Owns:** Tenants, users, roles, API keys; maps OIDC claims to roles; issues partner API keys; enforces plan limits; the audit log's table, `audit.event`
- **Owning team:** Identity and Partner (guide section 14)
- **Consumes:** Keycloak events; admin API
- **Emits / publishes:** tenant.created, user.role.changed, tenant.deletion.requested and its own tenant.data.erased (through the outbox)
- **Consumes (worker):** tenant.deletion.requested (group `identity.erasure`) and tenant.data.erased (group `identity.erasure-records`)

## What is here

| Route | Purpose |
| --- | --- |
| `POST /v1/identity/sessions` | Exchange an identity provider token for an access token; 404 `identity-user-not-provisioned` when the person has no user yet (the web's cue for sign-up), 403 `identity-mfa-required` when their roles need a second factor the sign-in lacked |
| `POST /v1/identity/tenants` | Sign-up: a business or CA firm tenant from the provider token of the person signing up, who becomes its first user (owner or CA admin); answers the tenant, the user and a session |
| `GET /v1/identity/me` | The signed-in user: tenant, roles, session version and whether they signed in with a second factor (a user's bearer token) |
| `GET /v1/identity/users` | The tenant's users (tenant admins) |
| `POST /v1/identity/users` | Invite a user by email address or phone number with roles the tenant's kind allows: their account at the identity provider, then the user (tenant admins) |
| `PUT /v1/identity/users/{user_id}/roles` | Change a user's roles; the user's older sessions are revoked (tenant admins) |
| `POST /v1/identity/users/{user_id}/disable` | Disable a user: no more sign-ins, sessions revoked (tenant admins) |
| `GET /v1/identity/users/{user_id}/membership` | Whether a user belongs to the tenant, with their roles and status and no contact details, for a service acting for it with tenant:act (the obligation service checks an assignee); a person's token is refused, and 404 names no such user or tenant |
| `POST /v1/identity/service-tokens` | Exchange a service client's id and secret for a service token with the client's scopes |
| `GET /v1/identity/.well-known/jwks.json` | The public keys every service verifies access tokens with |
| `POST /v1/identity/dev/provider-tokens` | Development sign-in: a fake provider token for a phone number or an email address; only with `CW_AUTH_PROVIDER=fake` in local and test, 404 elsewhere |
| `POST /v1/identity/consents` | Record a consent (`granted: true` needs `notice_version`) or a withdrawal; append-only |
| `GET /v1/identity/consents?subject=` | Current state per purpose and the full history for a subject (a user id or an E.164 number) |
| `POST /v1/identity/channel-consents` | Record a keyword opt-in or opt-out for a number (service token); 201, or 200 with the stored record when the message was recorded already |
| `GET /v1/identity/channel-consents/{channel}/{subject}` | A number's current state per purpose on a channel, with its history (service token) |
| `GET /v1/identity/audit` | The audit trail, newest first, a keyset page of at most 200: a tenant's entries for its owners, CA admins and compliance leads; the platform's (and the internal tenant's) for analysts, reviewers and admins; 403 for any other role or a service, 422 for a bad cursor or range |
| `GET /v1/identity/billing/plans` | The plans (placeholders with zero prices until pricing is decided) |
| `POST /v1/identity/billing/subscriptions` | Start a subscription with the provider (`Idempotency-Key` required: a retry with the same key and body gets the first answer and starts nothing more; another body is a 422); 503 while `CW_BILLING_PROVIDER=none` |
| `POST /v1/identity/billing/webhook` | Provider webhook; the body is verified against the webhook secret (`X-Razorpay-Signature`) before it is read; 200 with `ignored` when it names no tenant, `duplicate` when the tenant received the same body before |
| `GET /v1/identity/entitlements` | What the tenant's plan entitles it to: the plan, its status, the `registrations` and `seats` limits (null is none) and whether they are `enforced`; a user's own tenant, or a service with `entitlements:read` naming the tenant in `x-tenant-id` |
| `POST /v1/identity/data-requests` | Ask for a copy of the tenant's data (`kind` export) or its deletion (`kind` deletion: the tenant is shut at once and every service erases it), due 30 days later; the tenant's owner or CA admin, or the regulatory team's admin naming the tenant in `tenant_id` as a support request with a reason; 403 `identity-tenant-deleting` once the tenant asked for its deletion, 422 `identity-tenant-not-erasable` for the internal tenant |
| `GET /v1/identity/data-requests`, `GET /v1/identity/data-requests/{request_id}` | The tenant's requests, newest first, or one (404 `identity-data-request-not-found`), each with its deadline, whether it is overdue, the services that answered it (held its export, or erased the tenant) and those still pending; owners and CA admins, of a tenant being deleted too |
| `GET /v1/identity/data-requests/{request_id}/export` | The export as a JSON attachment, assembled now and never stored (409 `identity-export-not-ready` for a request that is not an export); owners and CA admins |
| `GET /v1/identity/erasures/{tenant_id}` | What identity holds of a tenant's deletion, which every other service's erasure consumer checks before erasing: the tenant's `status`, whether it is `internal`, and the `deletion_event_id` it last sent for the open deletion request (null when none); 404 `identity-tenant-not-found`; a service with `erasure:verify` (internal listener only) |

Purposes: `terms`, `privacy_notice`, `profile_processing`, `whatsapp_reminders`,
`email_reminders`, `analytics`. Sources: `web_onboarding`, `web_settings` (a change made later
on the web settings pages), `whatsapp_keyword`, `api`, `support`. The notice versions are the
`Version:` lines in `docs/legal`.

Channel consents (`identity.channel_consent`) are what a person asked for by writing a keyword
to the WhatsApp number before they have an account: START records a grant of
`whatsapp_reminders`, STOP a withdrawal. The WhatsApp bot is the caller. Rows carry no tenant,
so the table has no row-level security (the exemption is in
`infra/scripts/migration_lint.toml`); the routes need the shared secret
`CW_IDENTITY_CHANNEL_TOKEN` in `x-cw-service-token`, compared in constant time. Unset, both
routes answer 503; a missing or wrong token is a 401. With `CW_AUTH_MODE=dual` or `token` a
service token with the `identity:channel-consents` scope opens them too, and in `token` mode it is
the only way in. The subject is the E.164 number without
the plus, as WhatsApp reports it. A grant needs `notice_version`; the source is
`whatsapp_keyword`. The table is append-only (UPDATE and DELETE are refused by a trigger), and
a partial unique index on (channel, message_id) makes a redelivered webhook return the record
of its first delivery. A channel consent stays the keyword evidence of that number: the tenant
user's own `whatsapp_reminders` consent is recorded in `consent_record` at web onboarding, and
nothing links the two (docs/legal/consent-record.md).

Data requests. A tenant's owner or CA admin asks for a copy of the tenant's data (an export),
or the regulatory team's admin records one for a tenant that asked support. The request is due
30 days after it was made (`docs/legal/data-map.md`; counsel to confirm). An export is answered
as soon as it is made: it is `in_progress` (offered for download) until a download has had every
service's part, then `completed`. One the tenant never completes expires quietly at its deadline:
it is no longer open and never overdue, since only the tenant can complete it. Only a request
still `received`, never answered, is overdue past its deadline, and so is a deletion not
completed, whatever its status. The export is assembled on download and never stored: identity's own data of the
tenant (the tenant, its users, its consent records, its billing customer, subscriptions and
webhooks, its data requests; the growing ones read 500 rows at a time) and the part each service
of `CW_IDENTITY_EXPORT_SOURCES` answers on `GET /v1/<service>/data-export` (profile, the
applicability engine, obligation, notification; `service=url` pairs, the dev ports by default and
required outside local and test, each https or loopback; the internal listener in the combined
product). Identity calls each with a token it mints for that call: `data:export` only, bound to
the tenant (`tid`) and addressed to that one service (`aud` `compliancewatch:<service>`), for two
minutes, so a token that leaks cannot be replayed for another tenant or at another service. The
services are asked four at a time, 20 seconds each at most and 45 seconds for all
(`CW_IDENTITY_EXPORT_CONCURRENCY`, `CW_IDENTITY_EXPORT_TIMEOUT_SECONDS`,
`CW_IDENTITY_EXPORT_DEADLINE_SECONDS`), and the answer is written a service at a time. A source
that fails, is late or answers for another tenant is named in `services_pending` and its entry
says why; the download still answers 200. Two downloads at once each add the services that
answered them (the request's row is locked while they are recorded). No secrets reach the bundle
(no session versions, service clients, idempotency keys, checkout links, webhook digests or the
platform's own payment account id), and a support request shows `support` as who asked; the
tenant's audit trail names the admin who recorded it, as it names every actor. The table is
`data_request` (migration 0010), under forced row-level security; `data_request.created` and
`data_request.exported` go to the tenant's audit trail. Once identity has erased a tenant, its
tenant routes answer 410 `tenant-erased` (its `erased_tenant` marker).

Deletion (the erasure cascade; `docs/runbooks/data-requests.md`). A deletion request turns the
tenant `deletion_requested` in the transaction that records it, with `tenant.deletion.requested`
(1.0.1) in the outbox, its event id kept on the request (`deletion_event_id`), and
`data_request.created`: the session exchange refuses the tenant's people (403
`identity-tenant-deleting`), its tokens open no identity route but its data requests and its
audit trail, and it asks for nothing more. The other services take a token issued before the
request until it expires, and answer 410 once they have erased the tenant. The internal tenant
is never erased (422 `identity-tenant-not-erasable`). The worker (`identity.worker`, `make worker
SERVICE=identity`, or `cw-mvp worker`) hosts two consumers:

- `identity.erasure` on tenant.deletion.requested: while the flag `identity.tenant_erasure`
  (`CW_TENANT_ERASURE_ENABLED`, per tenant with `CW_TENANT_ERASURE_TENANTS`; owner
  identity-partner, off) is off for the tenant it only logs `erasure.off`. On, it first checks
  the event against identity's records (`CheckErasure`): one for a tenant not being deleted, for
  the internal tenant, or that is not the event identity last sent for the tenant's open deletion
  request touches nothing, not even the provider; it writes `tenant.erasure_refused` and is
  dead-lettered at once. Otherwise it deletes every user's account at the identity provider, with
  no transaction open (an account already gone counts as deleted; one at another provider is
  listed with its user id, provider and subject in the log and the `tenant.erased` row, for the
  operator), then in one transaction under `app.erasure`: deletes `user_subject`, `app_user` and
  the idempotency keys; pseudonymises `consent_record` (the subject becomes `erased:` and the
  first 32 hex digits of HMAC-SHA256 keyed with `CW_IDENTITY_ERASURE_PEPPER` over
  tenant|subject, the evidence is emptied and `recorded_by` nulled) and the billing customer's
  email (the same pseudonym) and name (emptied), keeping the provider's ids, the subscriptions,
  starts and masked webhooks for the tax records (for the lawyer to confirm); empties their
  checkout links; keeps the data requests; empties the tenant's name and marks it `erased`;
  prunes its published events; and writes `tenant.data.erased` (service identity), its
  `tenant.erased` audit row and its erased marker. Run again, it counts only what it changed.
- `identity.erasure-records` on tenant.data.erased: each service's answer to the event identity
  last sent joins the tenant's open deletion request (`data_request.erased`). Once every service
  of `CW_IDENTITY_ERASURE_SERVICES` (identity, profile, obligation, notification,
  applicability-engine, rulebook by default) has answered, it writes the second pass to the outbox
  held back `CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS` (900, longer than an access token lives;
  `data_request.second_pass_scheduled`), and the request completes (`data_request.completed`)
  once every service has answered that too.

`CW_IDENTITY_ERASURE_PEPPER` is a secret held outside the database: reversing a pseudonym needs
it, and counsel must still sign the formula off. It is required wherever the flag can be on (the
worker refuses to start without it) and `cw-mvp check-config` refuses it missing outside local
and test, where `DEV_ERASURE_PEPPER`, a documented placeholder, stands in.

Migration 0011 adds the consumers' `processed_event`, the consent records' guard (a trigger
refuses every DELETE, and lets an UPDATE through only under `app.erasure=on`) and lets an erased
tenant's name be empty. Migration 0012 adds the request's `deletion_event_id`, `second_pass_at`
and `second_pass_done`, the `erased_tenant` marker, makes the guard compare whole rows (only
subject, evidence and `recorded_by` may differ, so a column added later is guarded unnamed), and
makes an erased tenant's name empty and any other's not. With the flag off a deletion request
stays `received` and turns overdue after 30 days, which pages; `identity-admin erasure resend
--tenant ID --reason TEXT` sends the open request again once the flag is on, as the event the
services check (every erasure is idempotent). The audit log is never erased.

Counting every tenant's overdue requests needs to read past row-level security, so it goes
through `identity.data_requests_open()`: a `SECURITY DEFINER` function owned by the NOLOGIN role
`cw_identity_directory`, which has a read policy of its own on `data_request` and nothing else,
answering counts per kind (open, overdue) and no row. `infra/dev/postgres/roles.sql` makes the
role, the policy and the function once the table exists; only `cw_identity` and `cw_app` may run
it (the role grants that itself, as the function's owner). A schema owner that is not a superuser
is a member of the role WITH INHERIT FALSE, SET TRUE: it does not inherit the reads, but may SET
ROLE to read through the policy, as the runbook does, no more than the tables' owner could anyway. With telemetry on, the app reports `identity_data_requests_open{kind}` and
`identity_data_requests_overdue` from it, read at most once a minute; the DataRequestOverdue
alert pages on the second (`docs/runbooks/data-requests.md`).

Sign-in. People sign in at the identity provider and the web exchanges the provider's token at
`POST /v1/identity/sessions` for this service's access token, an ES256 JWT with the claims `iss`,
`aud`, `sub` (the user id), `kind`, `tid` (the tenant), `roles`, `scp`, `sv` (the session
version), `mfa`, `iat`, `exp` and `jti`, and `kid` in its header. Other services never see a
provider token, so they trust one issuer and a change of provider touches this service only. A
token lives ten minutes (`CW_ACCESS_TOKEN_TTL_SECONDS`). Changing a user's roles or disabling the
user bumps the session version: this service refuses older tokens at once (`/me` answers 401
`identity-session-revoked`), and other services stop accepting them when they expire. Analysts,
reviewers, admins and CA admins sign in with a second factor: the exchange refuses a sign-in whose
provider assurance level is not `aal2`. When the provider's keys cannot be fetched, sign-in fails
closed with 503 `identity-provider-unavailable`.

Tenants and users live in `identity.tenant` (row-level security on its own id) and
`identity.app_user` (row-level security by `tenant_id`); `identity.user_subject` maps a provider
subject to its user and tenant, and `identity.service_client` holds the service clients with the
SHA-256 of their secrets (both without row-level security, exempted with the reasons in
`infra/scripts/migration_lint.toml`). Tenant, user and consent reads also name the tenant in the
query, and the admin use cases check that the user they change belongs to the caller's tenant, so
tenants stay apart where row-level security does not apply (the dev stack connects as the
database's owner). `tenant.created` and `user.role.changed` leave through the outbox in the same
transaction as the change.

The audit log's table is identity's too: migration 0005 creates `audit.event` in the schema
`audit` (made when it is missing; the dev stack's `init.sql` makes it already), the one table
every service writes an audited action to, in the transaction of the action, through
`py_common.audit` (the py-common README describes the writer). Row-level security is forced: a
session reads and writes the rows of its tenant and may add rows of no tenant, for platform-wide
actions, which only the regulatory scope reads (below). A trigger refuses UPDATE and DELETE, a
tenant's erasure included, and `infra/scripts/migration_lint.toml` exempts the table because its tenant_id may be
null. The downgrade drops the table and keeps the schema.

Migration 0006 adds the read scopes: `event_platform_read` admits the rows of no tenant while the
transaction's `app.audit_scope` is `regulatory`, and `event_export_read` every row while it is
`export`, both FOR SELECT only. Identity sets the scope after its own role checks and names it in
the query too. Among the per-service roles only `cw_identity` may read the table; the MVP's one
image runs every service as `cw_app`, which holds SELECT on `audit` too, so there the scopes hold
by code convention (only identity's code sets them), as defence in depth rather than a role
boundary (docs/runbooks/audit-export.md). Migration 0007 adds the index on
(subject_type, subject_id, occurred_at) for one subject's history.
`GET /v1/identity/audit` reads it for people (filters `subject_type`, `subject_id`, `action`,
`from`, `to`; `limit` and `cursor`): owners, CA admins and compliance leads see their tenant's
entries, and analysts, reviewers and admins of the internal tenant (the route checks the kind as
well as the role) the platform's and the internal tenant's. A tenant
role never sees another tenant's rows or the platform's, and in header mode an anonymous caller
sees only the tenant its header names. `identity-admin audit-export --from --to --out DIR` writes
a range as NDJSON with `manifest.json` (SHA-256, count, range, generated_at), reading under the
export scope, into a missing or empty directory; the files keep `.partial` names until its
`audit.exported` row commits, and `--to` defaults to midnight UTC two days ago so late rows are
in. Uploading it to the object-locked bucket is a manual step
([docs/runbooks/audit-export.md](../../docs/runbooks/audit-export.md), which also lists every
service's audited actions). Rows are kept seven years and never changed.

Identity writes its own entries in the transaction of each change: `tenant.created` (sign-up, and
`bootstrap-internal`), `user.invited`, `user.roles_changed` and `user.disabled` (roles and status,
never a contact detail), `consent.recorded`, `subscription.started`, and by
`system:billing-webhook` `subscription.status_changed`, `subscription.event_ignored` (a late
event, or one after a cancellation) and `subscription.unmatched` (a webhook for a subscription
the tenant may not hold), and from `identity-admin` `service_client.created`,
`service_client.revoked` and `audit.exported` (by `system:identity-admin`). Channel consents and
the dev service clients made at start are not audited. A tenant's deletion writes
`data_request.created`, then `tenant.erased` (by `system:identity`, with the row counts),
`data_request.erased` per service that answered and `data_request.completed`; `identity-admin
erasure resend` writes `data_request.resent` (by `system:identity-admin`).

Billing ledger (migrations 0008 and 0009, `identity.billing_customer`, `billing_subscription`,
`billing_start` and `billing_event`, all under forced row-level security): a tenant's provider
customer, its subscriptions with their plan, quantity and status, the starts it asked for, and
every verified webhook, append-only (a trigger refuses UPDATE, and DELETE outside a tenant
erasure).

- **One provider subscription per Idempotency-Key.** `StartSubscription` records the start
  (`billing_start`, keyed by tenant and key) in its own transaction before it calls the provider.
  The tenant's provider customer is made once and stored at once; two first starts racing each
  other keep the customer stored first. The provider's answer is noted on the start, then the
  subscription and `subscription.started` are stored in one transaction. A retry with the same
  key never calls the provider again: it gets the stored subscription (recorded from the start's
  note if the ledger write had failed), or 409 `identity-subscription-start-pending` when the
  start failed after the provider may have created the subscription. A failure before the
  subscription was asked for, or a refusal by the provider (nothing created), frees the key.
- **Webhooks.** Verified first, then dedupled per tenant by the SHA-256 of the body (unique
  (tenant_id, body_sha256)). The event is stored as a projection on an allowlist, never the body:
  the event's kind, time and id (`x-razorpay-event-id`), and of the subscription, payment and
  invoice entities only their ids, plan, status, quantity, times, amounts and currency (and the
  notes `tenant_id` and `plan_key`), masked for personal identifiers as well. Names, emails, phone
  numbers, VPAs, addresses and card or bank details are never stored.
- **Order.** The subscription keeps the time of the last event applied (`last_event_at`); an
  older event that arrives later is stored, changes nothing and is audited as
  `subscription.event_ignored`. Cancelled is final: no later event makes it active again.
- **Adoption.** A webhook for a subscription the tenant does not hold records it
  (`subscription.started` by `system:billing-webhook`) only when the payload's customer is the
  tenant's stored provider customer and the tenant exists, which covers a start whose last
  write failed. Otherwise nothing changes, the event is audited as `subscription.unmatched`, and
  the answer is 200 `ignored` with a warning: a webhook never creates a subscription from its
  notes alone, and a subscription id another tenant holds is never moved (a tenant-guarded
  insert, never a 500 that the provider would retry).
- **Quantities** stay within 1..`CW_PLAN_MAX_QUANTITY` (1000; it can lower the API's ceiling,
  not raise it), from a request or a webhook.

A webhook finds its tenant only in the subscription's notes, which this service sets when it
creates it; one without is logged and answered as ignored.

Entitlements: the plan of the tenant's newest active subscription, or past-due one within the
grace, times its quantity, or the free allowance (`CW_PLAN_FREE_REGISTRATIONS` and
`CW_PLAN_FREE_SEATS`, one each); the internal tenant has no limits. A past-due subscription
(Razorpay's `pending`, and `halted` once it stopped retrying) keeps its plan for
`CW_PLAN_PAST_DUE_GRACE_DAYS` (14) after it turned past due, then the tenant has the free
allowance until a charge succeeds. With the flag `identity.plan_limits` on for a tenant
(`CW_PLAN_LIMITS_ENFORCED=true`, optionally `CW_PLAN_LIMITS_TENANTS=<ids>`; default off), an
invitation past the seats (active users) is refused with 402 `identity-seat-limit-reached`, once
early and again with the tenant locked, before the provider's account is made, so a refused
invitation leaves no account behind; profile refuses a new GSTIN registration past the
registrations with 402 `profile-plan-limit-reached`. Both problems carry `limit` and `used`
(the `LimitProblem` schema in the specs), and nothing else about the tenant. **Placeholders,
decided by the maintainer with the pricing:** the plans' prices and limits
(`identity.domain.billing.PLANS`: per unit, the owner plan 5 registrations and 3 seats, the CA
plan 25 and 1), the free allowance, and the past-due grace of 14 days.

Roles depend on the tenant's kind: a business has owners, staff and compliance leads; a CA firm has
CA admins, CA staff and compliance leads; the internal tenant has analysts, reviewers and admins.
Tenant admins (owners, CA admins, and admins of the internal tenant) manage users. With a verified
token the admin's own session version is checked against the store first, so an admin whose roles
changed a moment ago is refused at once. In dual mode these routes need the token (401
`auth-token-required` without one), since the users and roles they store outlive the switch to
token mode. In header mode the tenant header names the tenant as on every tenant route, and an
anonymous caller grants no owner, CA admin, analyst, reviewer or admin role (403
`auth-forbidden`). The last active admin of a tenant can be neither demoted nor disabled; role
changes and disables lock the tenant's row, so two of them at once cannot both pass that check. The internal tenant is set up once by an operator with
`identity-admin bootstrap-internal`, which creates its first admin at the identity provider; that
admin enrols a second factor there before signing in, then invites the analysts and reviewers.

Service clients (the pipeline, the WhatsApp bot, qa and the other services that call each other)
exchange their id and secret for a service token with their scopes. `identity-admin` creates them:

```bash
identity-admin signing-key new --kid 2026-10          # a key set for CW_IDENTITY_SIGNING_KEYS
identity-admin service-client create --id pipeline --scope rulebook:write --scope llm:call
identity-admin service-client revoke --id pipeline
identity-admin service-client list
identity-admin bootstrap-internal --name "Regulatory team" --email admin@example.org
identity-admin audit-export --from 2026-09-01 --to 2026-10-01 --out var/audit-export/2026-09
```

In local and test runs, with `CW_IDENTITY_DEV_CLIENT_SECRET` set, the service creates the clients
in `src/identity/identity_dev_clients.toml` with that secret when it starts; each caller then runs
with `CW_SERVICE_CLIENT_SECRET` set to the same value.

Settings: `CW_AUTH_PROVIDER=fake|supabase` (production refuses `fake`), with
`CW_IDENTITY_FAKE_PROVIDER_SECRET` for fake tokens several dev processes accept, and
`CW_SUPABASE_URL`, `CW_SUPABASE_SERVICE_ROLE_KEY` (secret) and `CW_SUPABASE_JWT_SECRET` (legacy
HS256 projects only) for Supabase; `CW_IDENTITY_SIGNING_KEYS` (secret; required outside local and
test, where a key is made at start with a warning); `CW_ACCESS_TOKEN_TTL_SECONDS` and
`CW_SERVICE_TOKEN_TTL_SECONDS` (600); `CW_IDENTITY_DEV_CLIENT_SECRET` and
`CW_IDENTITY_DEV_CLIENTS` (local and test only); `CW_IDENTITY_STORE=memory|postgres`; `CW_IDENTITY_CHANNEL_TOKEN` (secret; the bot
sends the same value as `IDENTITY_SERVICE_TOKEN`); `CW_BILLING_PROVIDER=none|memory|razorpay` with
`CW_RAZORPAY_KEY_ID`, `CW_RAZORPAY_KEY_SECRET`, `CW_RAZORPAY_WEBHOOK_SECRET` and
`CW_RAZORPAY_PLAN_IDS=owner_monthly=plan_x,ca_seat_monthly=plan_y`; `CW_PLAN_FREE_REGISTRATIONS`
and `CW_PLAN_FREE_SEATS` (1 each). Manual steps before
`razorpay` works: a Razorpay account, plans matching `identity.domain.billing.PLANS`, a
webhook to `/v1/identity/billing/webhook` with a secret, API keys. Nothing is created by code.
The OpenAPI spec is `packages/contracts/openapi/identity.v1.json` (`make openapi SERVICE=identity`).

`tools/demo/tests/unit/test_token_flow.py` runs the whole path in one process: a fake provider
token, sign-up, the session exchange, the profile service in token mode accepting the ES256 token
and refusing a request without it or for another tenant, a service client acting for a tenant,
and a disabled user refused by identity at once while profile accepts the token until it
expires. [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md) has the same steps
with curl against running services, and ADR-014's addendum records the design choices.

## Supabase: manual steps

Nothing in this repository creates a Supabase project or changes its settings. Until the project
exists, identity runs with `CW_AUTH_PROVIDER=fake`, which production refuses. The maintainer's
steps, in order:

1. Create the Supabase project in the Mumbai region and confirm the region in the project's
   settings (ADR-014: personal data stays in India).
2. Enable phone sign-in with an SMS provider Supabase supports, and confirm with that provider
   that phone numbers and messages stay in India. Record the answer with the DPDP data map.
3. Enable email sign-in, asymmetric JWT signing keys (so the project publishes its keys at
   `<project url>/auth/v1/.well-known/jwks.json`), TOTP multi-factor authentication, and an
   access token expiry of one hour or less.
4. Store the project URL as `CW_SUPABASE_URL` and the service-role key as the secret
   `CW_SUPABASE_SERVICE_ROLE_KEY` on identity, then set `CW_AUTH_PROVIDER=supabase`. Set
   `CW_SUPABASE_JWT_SECRET` only while the project still signs with its legacy HS256 secret.
5. For each environment, make identity's signing key with
   `identity-admin signing-key new --kid <yyyy-mm>` and store the printed key set as the secret
   `CW_IDENTITY_SIGNING_KEYS`. Every environment gets its own key.
6. For each environment, create the service clients with `identity-admin service-client create`,
   with the scopes `src/identity/identity_dev_clients.toml` gives each caller (today notification,
   obligation, pipeline, qa and the WhatsApp bot). Store each printed secret on its caller as
   `CW_SERVICE_CLIENT_SECRET` and the client id as `CW_SERVICE_CLIENT_ID` (the bot's are
   `BOT_SERVICE_CLIENT_SECRET` and `BOT_SERVICE_CLIENT_ID`). A secret is printed once.
7. Create the internal tenant and its first admin with
   `identity-admin bootstrap-internal --name ... --email ...`. Admins need a second factor, so the
   admin enrols a TOTP factor at Supabase before the first sign-in, then invites the analysts and
   reviewers.
8. Sign a person in on staging end to end. The adapter has been checked against synthetic tokens
   and recorded answers only, so this first sign-in is the check of the key set's path, the issuer
   (`<project url>/auth/v1`), the `authenticated` audience, the `aal` claim and the admin API that
   invitations use.
9. Move staging to `CW_AUTH_MODE=dual`, then to `token` once the web signs in with tokens and
   every caller sends its service token; production accepts only `token`. Then move ADR-014 to
   Accepted.

The secrets these steps create rotate as `docs/runbooks/secret-rotation.md` describes.

## Layout

```
src/identity/
  api/             # routers, request/response schemas, auth dependencies
  domain/          # tenancy.py: Tenant, User, roles by tenant kind; provider.py: IdentityProvider; sessions.py: TokenMinter; service_clients.py; events.py; repository.py: the unit of work; consent.py, channel_consent.py, billing.py (plans, the ledger port), entitlements.py, flags.py, data_requests.py (DataRequest, its deadline, the ExportSource and directory ports)
  application/     # tenancy.py: CreateTenant, CurrentUser, InviteUser, ChangeRoles, DisableUser, ListUsers, ReadMembership; sessions.py: ExchangeSession, IssueServiceToken; bootstrap.py: BootstrapInternalTenant, service clients; consents.py, channel_consents.py, billing.py, entitlements.py (ReadEntitlements, SeatCheck), data_requests.py (RequestExport, ListDataRequests, ReadDataRequest, ExportTenantData)
  infrastructure/  # memory.py, models.py, repository.py (Postgres, RLS, outbox, the billing ledger); minter.py; flags.py; providers/{fake,supabase}.py; billing/{memory,razorpay}.py; export_sources.py (HttpExportSource); data_request_metrics.py (the open and overdue gauges)
  admin.py         # identity-admin: signing keys, service clients, the internal tenant
  composition.py   # the identity provider CW_AUTH_PROVIDER names
  identity_dev_clients.toml  # the service clients local and test runs create
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
make migrate SERVICE=identity
make run SERVICE=identity           # http://localhost:8001/health, /ready, /v1/identity/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/identity/Dockerfile -t compliancewatch-identity .
```

Package `identity`, dev port 8001, Postgres schema `identity`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md), whose "Signing in with tokens" section runs identity in token mode and signs in with curl.

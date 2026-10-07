# identity service

Part of the ComplianceWatch monorepo. **Tenants, users and roles (row-level security, events through the outbox), sign-in through an identity provider (a fake one locally, Supabase Auth in the MVP, ADR-014), the access tokens every service verifies (ES256, published as a JWKS), service tokens for service clients, consent records (append-only) with their API, channel consents for WhatsApp numbers no tenant owns yet, and billing behind a flag: the `BillingProvider` protocol, an in-memory provider and a Razorpay skeleton.**
Design reference: Project Foundation guide, sections 7, 14 and 16.

- **Owns:** Tenants, users, roles, API keys; maps OIDC claims to roles; issues partner API keys; enforces plan limits; the audit log's table, `audit.event`
- **Owning team:** Identity and Partner (guide section 14)
- **Consumes:** Keycloak events; admin API
- **Emits / publishes:** tenant.created, user.role.changed (through the outbox)

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
| `POST /v1/identity/billing/subscriptions` | Start a subscription with the provider; 503 while `CW_BILLING_PROVIDER=none` |
| `POST /v1/identity/billing/webhook` | Provider webhook; the body is verified against the webhook secret (`X-Razorpay-Signature`) before it is read |

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
the query too, and among the service roles only `cw_identity` may read the table.
`GET /v1/identity/audit` reads it for people (filters `subject_type`, `subject_id`, `action`,
`from`, `to`; `limit` and `cursor`): owners, CA admins and compliance leads see their tenant's
entries, and analysts, reviewers and admins the platform's and the internal tenant's. A tenant
role never sees another tenant's rows or the platform's, and in header mode an anonymous caller
sees only the tenant its header names. `identity-admin audit-export --from --to --out DIR` writes
a range as NDJSON with `manifest.json` (SHA-256, count, range, generated_at), reading under the
export scope; uploading it to the object-locked bucket is a manual step
([docs/runbooks/audit-export.md](../../docs/runbooks/audit-export.md), which also lists every
service's audited actions). Rows are kept seven years and never changed.

Identity writes its own entries in the transaction of each change: `tenant.created` (sign-up, and
`bootstrap-internal`), `user.invited`, `user.roles_changed` and `user.disabled` (roles and status,
never a contact detail), `consent.recorded`, `subscription.started` and
`subscription.status_changed` (by `system:billing-webhook`), and from `identity-admin`
`service_client.created`, `service_client.revoked` and `audit.exported` (by
`system:identity-admin`). Channel consents and the dev service clients made at start are not
audited.

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
`CW_RAZORPAY_PLAN_IDS=owner_monthly=plan_x,ca_seat_monthly=plan_y`. Manual steps before
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
  domain/          # tenancy.py: Tenant, User, roles by tenant kind; provider.py: IdentityProvider; sessions.py: TokenMinter; service_clients.py; events.py; repository.py: the unit of work; consent.py, channel_consent.py, billing.py
  application/     # tenancy.py: CreateTenant, CurrentUser, InviteUser, ChangeRoles, DisableUser, ListUsers, ReadMembership; sessions.py: ExchangeSession, IssueServiceToken; bootstrap.py: BootstrapInternalTenant, service clients; consents.py, channel_consents.py, billing.py
  infrastructure/  # memory.py, models.py, repository.py (Postgres, RLS, outbox); minter.py; providers/{fake,supabase}.py; billing/{memory,razorpay}.py
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

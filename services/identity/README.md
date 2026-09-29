# identity service

Part of the ComplianceWatch monorepo. **Tenants, users and roles (row-level security, events through the outbox), sign-in through an identity provider (a fake one locally, Supabase Auth in the MVP, ADR-014), the access tokens every service verifies (ES256, published as a JWKS), service tokens for service clients, consent records (append-only) with their API, channel consents for WhatsApp numbers no tenant owns yet, and billing behind a flag: the `BillingProvider` protocol, an in-memory provider and a Razorpay skeleton.**
Design reference: Project Foundation guide, sections 7, 14 and 16.

- **Owns:** Tenants, users, roles, API keys; maps OIDC claims to roles; issues partner API keys; enforces plan limits
- **Owning team:** Identity and Partner (guide section 14)
- **Consumes:** Keycloak events; admin API
- **Emits / publishes:** tenant.created, user.role.changed (through the outbox)

## What is here

| Route | Purpose |
| --- | --- |
| `POST /v1/identity/sessions` | Exchange an identity provider token for an access token; 404 `identity-user-not-provisioned` when the person has no user yet (the web's cue for sign-up), 403 `identity-mfa-required` when their roles need a second factor the sign-in lacked |
| `POST /v1/identity/tenants` | Sign-up: a business or CA firm tenant from the provider token of the person signing up, who becomes its first user (owner or CA admin); answers the tenant, the user and a session |
| `GET /v1/identity/me` | The signed-in user: tenant, roles, session version and whether they signed in with a second factor (a user's bearer token) |
| `POST /v1/identity/service-tokens` | Exchange a service client's id and secret for a service token with the client's scopes |
| `GET /v1/identity/.well-known/jwks.json` | The public keys every service verifies access tokens with |
| `POST /v1/identity/dev/provider-tokens` | Development sign-in: a fake provider token for a phone number or an email address; only with `CW_AUTH_PROVIDER=fake` in local and test, 404 elsewhere |
| `POST /v1/identity/consents` | Record a consent (`granted: true` needs `notice_version`) or a withdrawal; append-only |
| `GET /v1/identity/consents?subject=` | Current state per purpose and the full history for a subject (a user id or an E.164 number) |
| `POST /v1/identity/channel-consents` | Record a keyword opt-in or opt-out for a number (service token); 201, or 200 with the stored record when the message was recorded already |
| `GET /v1/identity/channel-consents/{channel}/{subject}` | A number's current state per purpose on a channel, with its history (service token) |
| `GET /v1/identity/billing/plans` | The plans (placeholders with zero prices until pricing is decided) |
| `POST /v1/identity/billing/subscriptions` | Start a subscription with the provider; 503 while `CW_BILLING_PROVIDER=none` |
| `POST /v1/identity/billing/webhook` | Provider webhook; the body is verified against the webhook secret (`X-Razorpay-Signature`) before it is read |

Purposes: `terms`, `privacy_notice`, `profile_processing`, `whatsapp_reminders`,
`email_reminders`, `analytics`. Sources: `web_onboarding`, `whatsapp_keyword`, `api`,
`support`. The notice versions are the `Version:` lines in `docs/legal`.

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
`infra/scripts/migration_lint.toml`). `tenant.created` and `user.role.changed` leave through the
outbox in the same transaction as the change.

Service clients (the pipeline, the WhatsApp bot, qa and the other services that call each other)
exchange their id and secret for a service token with their scopes. `identity-admin` creates them:

```bash
identity-admin signing-key new --kid 2026-10          # a key set for CW_IDENTITY_SIGNING_KEYS
identity-admin service-client create --id pipeline --scope rulebook:write --scope llm:call
identity-admin service-client revoke --id pipeline
identity-admin service-client list
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

## Layout

```
src/identity/
  api/             # routers, request/response schemas, auth dependencies
  domain/          # tenancy.py: Tenant, User, roles by tenant kind; provider.py: IdentityProvider; sessions.py: TokenMinter; service_clients.py; events.py; repository.py: the unit of work; consent.py, channel_consent.py, billing.py
  application/     # tenancy.py: CreateTenant, CurrentUser; sessions.py: ExchangeSession, IssueServiceToken; bootstrap.py: service clients; consents.py, channel_consents.py, billing.py
  infrastructure/  # memory.py, models.py, repository.py (Postgres, RLS, outbox); minter.py; providers/{fake,supabase}.py; billing/{memory,razorpay}.py
  admin.py         # identity-admin: signing keys and service clients
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

Package `identity`, dev port 8001, Postgres schema `identity`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

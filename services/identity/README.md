# identity service

Part of the ComplianceWatch monorepo. **Consent records (append-only, row-level security) with their API, and billing behind a flag: the `BillingProvider` protocol, an in-memory provider and a Razorpay skeleton. Tenants, users and roles arrive with Supabase Auth (ADR-014).**
Design reference: Project Foundation guide, sections 7, 14 and 16.

- **Owns:** Tenants, users, roles, API keys; maps OIDC claims to roles; issues partner API keys; enforces plan limits
- **Owning team:** Identity and Partner (guide section 14)
- **Consumes:** Keycloak events; admin API
- **Emits / publishes:** tenant.created, user.role.changed

## What is here

| Route | Purpose |
| --- | --- |
| `POST /v1/identity/consents` | Record a consent (`granted: true` needs `notice_version`) or a withdrawal; append-only |
| `GET /v1/identity/consents?subject=` | Current state per purpose and the full history for a subject (a user id or an E.164 number) |
| `GET /v1/identity/billing/plans` | The plans (placeholders with zero prices until pricing is decided) |
| `POST /v1/identity/billing/subscriptions` | Start a subscription with the provider; 503 while `CW_BILLING_PROVIDER=none` |
| `POST /v1/identity/billing/webhook` | Provider webhook; the body is verified against the webhook secret (`X-Razorpay-Signature`) before it is read |

Purposes: `terms`, `privacy_notice`, `profile_processing`, `whatsapp_reminders`,
`email_reminders`, `analytics`. Sources: `web_onboarding`, `whatsapp_keyword`, `api`,
`support`. The notice versions are the `Version:` lines in `docs/legal`.

Settings: `CW_IDENTITY_STORE=memory|postgres`; `CW_BILLING_PROVIDER=none|memory|razorpay` with
`CW_RAZORPAY_KEY_ID`, `CW_RAZORPAY_KEY_SECRET`, `CW_RAZORPAY_WEBHOOK_SECRET` and
`CW_RAZORPAY_PLAN_IDS=owner_monthly=plan_x,ca_seat_monthly=plan_y`. Manual steps before
`razorpay` works: a Razorpay account, plans matching `identity.domain.billing.PLANS`, a
webhook to `/v1/identity/billing/webhook` with a secret, API keys. Nothing is created by code.
The OpenAPI spec is `packages/contracts/openapi/identity.v1.json` (`make openapi SERVICE=identity`).

## Layout

```
src/identity/
  api/             # routers, request/response schemas, auth dependencies
  domain/          # consent.py: ConsentRecord, purposes, repository protocol; billing.py: Plan, Subscription, BillingProvider
  application/     # consents.py: RecordConsent, ConsentStatus; billing.py: StartSubscription, ReceiveBillingWebhook
  infrastructure/  # memory.py, models.py, repository.py (Postgres, RLS); billing/{memory,razorpay}.py
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

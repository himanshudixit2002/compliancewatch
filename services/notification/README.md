# notification service

Part of the ComplianceWatch monorepo. **Preferences (opt-in, opt-out, language, quiet hours), the template registry (English and Hindi drafts), the send use case (dedupe, consent, quiet hours, render, deliver, `notification.sent`/`notification.failed`) and the WhatsApp Cloud API channel behind a flag. Stores are in memory until the service's migration lands.**
Design reference: Project Foundation guide, sections 7 and 14.

- **Owns:** Notifications, channel adapters (WhatsApp, SES), preferences; dedupe by key, digests, quiet hours, template rendering per channel and language
- **Owning team:** Core Product (guide section 14)
- **Consumes:** obligation.created, obligation.due_soon, digest schedules
- **Emits / publishes:** notification.sent, notification.failed

## What is here

| Route | Purpose |
| --- | --- |
| `PUT /v1/notification/preferences/{channel}/{recipient}` | Record an opt-in or opt-out (no tenant: an opt-out must be honoured before the number is linked to a tenant) |
| `GET /v1/notification/preferences/{channel}/{recipient}` | The recorded preference |
| `POST /v1/notification/send` | One notification (tenant header required): `sent`, `failed`, `deferred` (quiet hours, with `scheduled_for`), `not_opted_in` or `duplicate` |
| `GET /v1/notification/templates` | Every template with its Meta approval status |

Quiet hours default to 21:00 to 08:00 IST (`CW_QUIET_HOURS_START`, `CW_QUIET_HOURS_END`) and
can be set per recipient. The WhatsApp channel is wired only with `CW_WHATSAPP_ENABLED=true`,
`CW_WHATSAPP_PHONE_NUMBER_ID` and `CW_WHATSAPP_ACCESS_TOKEN`; otherwise every WhatsApp send
returns a failed receipt saying the channel is disabled. Templates are drafts until the
maintainer submits them to Meta; `docs/runbooks/whatsapp.md` lists the steps. The inbound
side (webhook, keywords) is `apps/whatsapp-bot`, which calls the preference routes.

## Layout

```
src/notification/
  api/             # routers, request/response schemas, auth dependencies
  application/     # send.py: SendNotification; preferences.py: SetOptIn
  domain/          # preferences.py (QuietHours, ChannelPreference), templates.py (registry, render), model.py, events.py
  infrastructure/  # memory.py stores; whatsapp.py: WhatsAppCloudChannel, DisabledChannel
  testing.py       # FakeChannel and settings builder for tests
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
make migrate SERVICE=notification
make run SERVICE=notification           # http://localhost:8006/health, /ready, /v1/notification/ping
make test                         # unit + contract tests with the coverage gate
docker build -f services/notification/Dockerfile -t compliancewatch-notification .
```

Package `notification`, dev port 8006, Postgres schema `notification`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

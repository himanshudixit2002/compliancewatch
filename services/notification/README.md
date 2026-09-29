# notification service

Part of the ComplianceWatch monorepo. **Recipients per business, a Postgres store under row-level security, a worker that turns obligation events into change cards, reminders, deadline changes and closures (batching, quiet hours, retries, a fallback channel, daily digests for owners and CA firms, a retention sweep), delivery receipts with WhatsApp's 24-hour window, the WhatsApp Cloud API channel and an SMTP email channel, each behind a flag.**
Design reference: Project Foundation guide, sections 7, 9 and 14.

- **Owns:** Recipients and their addresses, notifications and their delivery state, channel adapters (WhatsApp, email over SMTP), preferences and suppressions; dedupe by occasion, batching, digests, quiet hours, template rendering per channel and language
- **Owning team:** Core Product (guide section 14)
- **Consumes:** obligation.created, obligation.due_soon, obligation.rescheduled, obligation.closed; delivery statuses forwarded by the WhatsApp bot; SES feedback through SNS
- **Emits / publishes:** notification.sent, notification.failed (1.0.1, through the outbox)

## What is here

| Route | Purpose |
| --- | --- |
| `PUT /v1/notification/preferences/{channel}/{recipient}` | Record an opt-in or opt-out for an address (no tenant: an opt-out must be honoured before the address is linked to a tenant). The address is normalised, so `919876543210` and `+91 98765 43210` are one record |
| `GET /v1/notification/preferences/{channel}/{recipient}` | The recorded preference |
| `PUT /v1/notification/recipients/{recipient_id}` | Register a recipient of the tenant, or replace it whole: role (`owner`, `staff`, `ca_admin`, `ca_staff`), language, digest mode, the CA firm's label, addresses in order, and the businesses it hears about. Registering an address gives no consent |
| `GET`, `DELETE /v1/notification/recipients/{recipient_id}` | Read or remove a recipient with its addresses and business links |
| `GET /v1/notification/recipients?business_id=&limit=&cursor=` | The recipients that follow a business, by id, a page at a time |
| `POST /v1/notification/send` | Send one notification now through the queue: `sent`, `failed` (the service retries it), `deferred` (quiet hours, with `scheduled_for`), `not_opted_in` or `duplicate`. The `attempt` field is deprecated and ignored |
| `GET /v1/notification/notifications?business_id=&state=&limit=&cursor=` | A business's notifications, newest first, a page at a time |
| `GET /v1/notification/notifications/{notification_id}` | One notification of the tenant with its state, attempts, error and delivery times |
| `POST /v1/notification/notifications/{notification_id}/resend` | Queue a notification that failed for good again (409 `notification-resend-not-allowed` in any other state) |
| `POST /v1/notification/receipts/whatsapp` | Statuses and inbound times the WhatsApp bot forwards, with `x-cw-bot-token` (`CW_NOTIFICATION_BOT_TOKEN`; unset, 503; missing or wrong, 401) or its service token (see Authentication) |
| `POST /v1/notification/receipts/email` | SES bounces, complaints and deliveries that SNS posts, with HTTP basic credentials whose password is `CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN`, and the SNS signature verified |
| `GET /v1/notification/templates` | Every template with its Meta approval status |

The recipient, send and notification routes act for one tenant, checked before the body (a
request without one is a 401 `notification-tenant-required` problem). The spec is
committed at `packages/contracts/openapi/notification.v1.json`
(`make openapi SERVICE=notification`) and pinned by `tests/contract/test_openapi.py`; the
schemathesis properties in `tests/contract/test_api_properties.py` cover every route, in header
mode and, for the routes that read a token, in token mode.

### Authentication

The caller comes from `py_common.auth` by `CW_AUTH_MODE` (`api/deps.py`). In `header` mode (the
default) no token is read: the tenant is the `x-tenant-id` header and the bot's receipts carry
`x-cw-bot-token`, as before tokens existed. In `dual` mode a request with a bearer token is served
as in `token` mode and one without it as in `header` mode; in `token` mode a bearer is required
(401 `auth-token-required`). With a token:

| Routes | Who may call |
| --- | --- |
| preferences | a service with `notification:preferences` (the WhatsApp bot); no user, since preferences name no tenant |
| `POST /send` | a service with `notification:send`, naming the tenant in `x-tenant-id` with `tenant:act` |
| recipients, notifications | a user with a tenant member role, whose token names the tenant (an `x-tenant-id` naming another is a 403 `auth-tenant-mismatch`), or a service with `tenant:act` naming it |
| `POST /receipts/whatsapp` | a service with `notification:receipts`; `x-cw-bot-token` is accepted only in `header` and `dual` mode |
| `POST /receipts/email`, `GET /templates` | read no token: SNS posts with basic credentials, and the templates are the same for everyone |

A caller without the role or scope gets a 403 `auth-forbidden`. The dispatcher reads rule versions
from the rulebook with the service's own access token once `CW_SERVICE_CLIENT_SECRET` is set (its
client is `notification`, with no scope; `CW_SERVICE_CLIENT_ID` defaults to it under `make run` and
`make worker`); identity refusing the client is an outage of the rulebook, retried later.
`tests/unit/test_auth_mode.py` covers the three modes.

### From an obligation event to a message

The worker consumes the obligation events in group `notification.obligations`.
`domain/routing.py` (`EVENT_ROUTES`) decides what each event sends:

- `obligation.created`: a `change_card` (what changed, that it applies, from when, what to do);
- `obligation.due_soon`: `obligation_due_soon`, one per reminder number;
- `obligation.rescheduled`: `obligation_deadline_extended` or `obligation_corrected`; a manual
  reschedule sends nothing;
- `obligation.closed`: `obligation_withdrawn` when the rule was withdrawn, `obligation_closed`
  when the business profile changed or a newer rule version replaced the rule; the user's own
  completion or waiver sends nothing.

`EnqueueNotifications` fans the event out to the business's recipients. Each gets one
notification on its first open address (opted in and not suppressed), keyed by the occasion
(`domain/occasions.py`): one change card per rule version, business, recipient and channel; one
reminder per obligation, reminder number, recipient and channel; one closure per obligation,
recipient and channel; one reschedule per obligation, new due date, recipient and channel. The
key is unique in the store, so a redelivered event queues nothing twice. The notifications are
queued in the consumer's own transaction, so they and the consumer's `processed_event` row
commit together. A message the handler cannot read goes to
`<topic>.notification.obligations.dlq` after the consumer's retries.

`DispatchDue` runs every `CW_NOTIFICATION_DISPATCH_INTERVAL_SECONDS` (5). It claims due work
with a 60-second lease (`FOR UPDATE SKIP LOCKED`, so several workers can run side by side) and
renews the lease of each message's notifications just before it sends that message, so a long
claim is never sent twice by a second worker; a message whose notifications another worker
claimed meanwhile is left to that worker. It checks consent and suppression again, and holds a notification in quiet hours (21:00 to 08:00
IST by default, `CW_QUIET_HOURS_START` and `CW_QUIET_HOURS_END`, or the address's own) until
they end. Notifications to one person, business and channel that fall in one batching window
(`CW_NOTIFICATION_BATCH_WINDOW_SECONDS`, 300; 0 sends each alone) go as one `batch_summary`.
A recipient with a daily digest, and every person of a CA firm, gets them held until
`CW_NOTIFICATION_DIGEST_AT` (09:00 IST) and then as one `daily_digest` or `ca_digest`. The
message is filled with the rule version's published facts from the rulebook
(`CW_RULEBOOK_URL`, cached for an hour) and links to `CW_WEB_BASE_URL`. A rule version the
rulebook does not know goes out as `obligation_created`, which states only the obligation's own
facts; a rulebook outage puts the notification back for 60 seconds without spending an attempt
(counted as `rescheduled`, and aged by the pending-work gauge until it goes), and a rulebook
that refuses the read (a 4xx other than 404, 408 and 429) fails the message without retries.

A failed attempt is retried after 60 and 300 seconds. The third failure fails the notification,
publishes `notification.failed` with `will_retry` saying whether a fallback follows, and queues
the fallback on the recipient's next open address on another channel; a fallback never falls
back again. A message that cannot be rendered is not retried. `POST /send` goes through the
same queue: it queues the notification due at once and hands it straight to the dispatcher,
outside the batching window.

### Receipts and the 24-hour window

The WhatsApp bot forwards Meta's statuses (sent, delivered, read, failed) and the times each
number wrote to the business. A status only moves a notification forward (sent, then
delivered, then read); a failure after it was sent fails it, publishes `notification.failed`
and queues its fallback. An inbound time opens WhatsApp's 24-hour customer service window:
inside it the channel sends free text, outside it only a template Meta approved. Every template
is still a draft, so until Meta approves them a business-initiated WhatsApp message outside the
window fails at once and the email fallback goes without waiting for retries.

Email goes out over SMTP only with `CW_EMAIL_ENABLED=true` (the `notification.email` flag, off
by default, owner core-product; removed once the in-region SES or SMTP sending domain is
verified and email has run in production for 30 days, after which the channel is wired
whenever `CW_SMTP_HOST` is set), `CW_SMTP_HOST` and `CW_EMAIL_FROM`. The connection needs
STARTTLS; the channel logs in when `CW_SMTP_USERNAME` is set, and every message carries its
dispatch id in the `X-CW-Dispatch-Id` header, by which SES's reports find it. SES feedback
comes through SNS: the route accepts only SignatureVersion 2 signatures by a certificate on
`https://sns.<region>.amazonaws.com/`, and only the topic `CW_NOTIFICATION_SES_TOPIC_ARN` when
that is set. SNS signs with version 1 by default, so before subscribing set the topic to
version 2: `aws sns set-topic-attributes --topic-arn <arn> --attribute-name SignatureVersion
--attribute-value 2`, or in the SNS console edit the topic and set its message signature version
to 2 (SHA-256); otherwise even the subscription confirmation is refused. The secret travels as
the SNS subscription's HTTP basic credentials, never in the
path, so logs and spans record the route template only. A permanent bounce or a complaint
suppresses the mailbox for every tenant. `docs/runbooks/notification-delivery.md` has the SES
setup and the alerts.

The WhatsApp channel is wired only with `CW_WHATSAPP_ENABLED=true`,
`CW_WHATSAPP_PHONE_NUMBER_ID` and `CW_WHATSAPP_ACCESS_TOKEN`; otherwise every WhatsApp send
fails saying the channel is disabled. The inbound side (webhook, keywords, status forwarding)
is `apps/whatsapp-bot`; its recorded calls are in
`packages/contracts/consumers/whatsapp-bot/notification.json`, and
`tests/contract/test_consumers.py` replays them against this service.

### Templates

`domain/templates.py` holds every template as a draft: WhatsApp in English and Hindi with its
Meta name (`cw_<key>_<language>`) and email in English. Besides the reminder and the opt-in and
opt-out confirmations there are `change_card`, `obligation_created`, `obligation_closed`,
`batch_summary`, `daily_digest`, `ca_digest` and the three deadline-change templates of ADR-015
(`obligation_deadline_extended`, `obligation_corrected`, `obligation_withdrawn`).
`ordered_params` gives the values in the order of the template's placeholders for a Meta
template send, and summary and digest lines are joined with `; ` on WhatsApp, which refuses
newlines in template values. Meta also refuses a template message whose filled body passes
1,024 characters, so on WhatsApp a summary's list gets only the room the rest of its template
leaves (its copy, the link, the label), and what does not fit is counted as 'and N more'; the
business or firm label a summary names is cut to 60 characters. The texts carry placeholders only, never a regulatory fact; the
facts come from the rulebook. The Hindi copy awaits analyst review, and each template waits for
Meta's approval (`docs/runbooks/whatsapp.md`).

### Store and retention

`CW_NOTIFICATION_STORE` is `postgres` (the default) or `memory` (tests and the demo). Migration
`20260929_0001_notification_store.py` creates the tenant tables `recipient`,
`recipient_address`, `recipient_business` and `notification` under forced row-level security,
and four tables without it, each with its reason in the table comment and in
`infra/scripts/migration_lint.toml`: `channel_preference` (consent per address before any
tenant link, and the last inbound time), `suppression` (bounced or complained mailboxes, for
every tenant), `address_directory` (which tenant an address belongs to) and `work_index` (the
dispatcher's queue across tenants, and the provider message id a receipt finds its tenant by).
The same migration creates the outbox and the consumer inbox.

The retention sweep runs daily at 03:00 IST: it deletes notifications older than two years and
empties the template values of those older than 30 days that are no longer pending (guide
section 9, `docs/legal/data-map.md`). Row-level security hides every notification from a unit
without a tenant, so it reads the tenants from `work_index` and `address_directory` and sweeps
one tenant at a time.

### Metrics and alerts

`infrastructure/metrics.py` emits exactly these series, exported when `CW_OTEL_ENDPOINT` is set.
The names are the programme's interface contract, which dashboards, SLOs and alerts use as
written here. `channel` is `whatsapp` or `email` on every series.

| Series | Labels | Meaning |
| --- | --- | --- |
| `notification_sends_total` (counter) | `channel`, `outcome` | One per notification each time the dispatcher takes it up. `sent`: the channel took it. `retry`: the attempt failed and another follows. `failed`: the last attempt failed (a fallback, if any, is a notification of its own). `suppressed`: the address opted out or was suppressed after the notification was queued, so it did not go. `rescheduled`: the rulebook could not fill the message, so it is due again a minute later with no attempt spent |
| `notification_delivery_lag_seconds` (histogram; `_bucket`, `_sum`, `_count`) | `channel` | Seconds from the moment a notification was planned to go out to the moment the channel took it, one per notification sent. The batching window, the digest time and quiet hours set that moment, so they are not delay; retries and rulebook outages do not move it, so they are. Buckets from 1 s to 6 h; 900 s is the 15-minute delivery objective |
| `notification_duplicate_sent_total` (counter) | `channel` | A delivery of a notification that was already sent: one delivery outlasted its whole lease and another dispatcher sent the message meanwhile. Should stay at zero |
| `notification_enqueued_total` (counter) | `channel`, `outcome` | Notifications that obligation events queued. `queued`, or `duplicate` for an occasion that already had its notification (a redelivered event), which is expected. `POST /send` and fallbacks are not counted here |
| `notification_receipts_total` (counter) | `channel`, `kind`, `outcome` | Provider reports after a message was taken: WhatsApp statuses the bot forwards and SES feedback. `kind`: `sent`, `delivered`, `read`, `failed`, `bounced` or `complained`. `outcome`: `applied` (it moved a notification on), `unchanged` (late, repeated, or for a notification in no state to take it) or `unknown` (no notification carries the message id, as with the bot's own replies) |
| `notification_pending_oldest_age_seconds` (gauge) | none | Seconds since the pending notification that has waited longest was planned to go out, 0 when none waits past its moment. The API process reports it, every replica the same queue across tenants, read at most every 30 s; a failed read reports nothing rather than 0 |

The older names in the WP13 brief body are not emitted. Their counterparts: sent and failed
attempts are `notification_sends_total{outcome="sent"}` and `{outcome=~"retry|failed"}`
(`failed` is the final one), a duplicate the dedupe key caught is
`notification_enqueued_total{outcome="duplicate"}`, a suppression is
`notification_sends_total{outcome="suppressed"}`, and the delivery time is
`notification_delivery_lag_seconds`.

The `notification` alert group (`NotificationDeliveryFailures`, `NotificationDuplicateSent`,
`NotificationPendingOverdue`, `NotificationEmailBounces`) reads them and links
`docs/runbooks/notification-delivery.md`.

## Layout

```
src/notification/
  api/             # router.py (preferences, send, templates), recipients.py, notifications.py, receipts.py, schemas, deps
  application/     # enqueue.py, dispatch.py, send.py (SendNow), fallback.py, receipts.py, email_feedback.py,
                   # resend.py, history.py, recipients.py, preferences.py, retention.py, consent.py
  domain/          # notification.py (states and transitions), occasions.py (dedupe keys), routing.py (EVENT_ROUTES),
                   # recipients.py, addresses.py, digest.py, policy.py, receipts.py, channels.py, templates.py,
                   # values.py, preferences.py, repository.py and ports.py (protocols), events.py, errors.py
  infrastructure/  # repository.py and work_index.py (Postgres), memory.py, whatsapp.py, email.py, ses_feedback.py,
                   # rulebook_client.py, events_in.py, metrics.py, models.py
  composition.py   # wire(settings): the use cases on the configured store, channels and rulebook reader
  worker.py        # components(settings): consumer, dispatcher, retention sweep (python -m notification.worker)
  testing.py       # fake channel, clock, rulebook reader, metrics and SNS, and a settings builder for tests
  main.py          # composition root of the HTTP app: build_app(settings, channels=...)
migrations/        # alembic (env.py reads CW_DATABASE_URL and CW_DB_SCHEMA)
tests/
  unit/            # domain and application with the memory store and fake channels; no I/O
  integration/     # testcontainers Postgres: migration, row-level security, dedupe, SKIP LOCKED, consumer path
  contract/        # OpenAPI spec and properties, event schemas, the bot's recorded calls
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                                 # infrastructure (Docker Compose)
make migrate SERVICE=notification
make run SERVICE=notification            # http://localhost:8006/health, /ready, /v1/notification/ping
make worker SERVICE=notification         # consumer, dispatcher and retention sweep
make relay SERVICE=notification          # publishes notification.sent and notification.failed
make test                                # unit + contract tests with the coverage gate
docker build -f services/notification/Dockerfile -t compliancewatch-notification .
```

The image runs the API by default; `python -m notification.worker` runs the worker from the same
image. The worker needs `CW_NOTIFICATION_STORE=postgres` and Kafka. Package `notification`, dev
port 8006, Postgres schema `notification`. Details:
[docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).

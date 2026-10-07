# notification service

Part of the ComplianceWatch monorepo. **Recipients per business, a Postgres store under row-level security, a worker that turns obligation events into change cards, reminders, deadline changes and closures (batching, quiet hours, retries, a fallback channel, daily digests for owners and CA firms, a retention sweep), a CA firm's bulk change card to its clients behind a flag, delivery receipts with WhatsApp's 24-hour window, the WhatsApp Cloud API channel and an SMTP email channel, each behind a flag.**
Design reference: Project Foundation guide, sections 7, 9 and 14.

- **Owns:** Recipients and their addresses, notifications and their delivery state, channel adapters (WhatsApp, email over SMTP), preferences and suppressions; dedupe by occasion, batching, digests, quiet hours, template rendering per channel and language
- **Owning team:** Core Product (guide section 14)
- **Consumes:** obligation.created, obligation.due_soon, obligation.rescheduled, obligation.closed; tenant.deletion.requested (group `notification.erasure`); delivery statuses forwarded by the WhatsApp bot; SES feedback through SNS
- **Emits / publishes:** notification.sent, notification.failed (1.0.1) and tenant.data.erased (through the outbox)

## What is here

| Route | Purpose |
| --- | --- |
| `PUT /v1/notification/preferences/{channel}/{recipient}` | Record an opt-in or opt-out for an address (no tenant: an opt-out must be honoured before the address is linked to a tenant). The address is normalised, so `919876543210` and `+91 98765 43210` are one record. An opt-in from the web needs identity's consent (below) |
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
| `POST /v1/notification/bulk` | A CA firm's change card to the clients a change affects, in the public API from 0.4.0 (below); 201 with the businesses by outcome, with an Idempotency-Key; 503 `notification-bulk-disabled` while `CW_NOTIFICATION_BULK_ENABLED` is off |
| `GET /v1/notification/data-export` | The tenant's data for its data export, which identity assembles: `recipients` (with their addresses and businesses), `preferences` (of the addresses the tenant's recipients hold, only those the tenant's own users set on the web, with only the consent, language and quiet hours) and `notifications`, each read 500 rows at a time. Suppressions, the address directory and the work index are not exported |

An opt-in given on the web (`opted_in` true with source `web_onboarding` or `web_settings`) is
recorded only when identity holds a granted consent for the channel's purpose, `whatsapp_reminders`
for WhatsApp and `email_reminders` for email, as docs/legal/data-map.md says a preference must be
backed, and, where identity holds the subject's phone (WhatsApp) or email, only for that
address. The service reads `GET {CW_IDENTITY_URL}/v1/identity/consents?subject=&channel=&address=`
for the request's tenant (`x-tenant-id`) with its own service token, which needs `tenant:act`. The
subject is the body's `subject`, the user id the web records consents under. Without a granted
consent the answer is a 409 `notification-consent-not-recorded`, for an address identity knows is
not the subject's a 409 `notification-consent-address-not-theirs`, without a tenant a 401
`notification-tenant-required`, without a subject a 422 `notification-consent-subject-required`,
and when identity cannot answer a 503 `notification-dependency-unavailable`; nothing is recorded in
any of these cases. Opt-outs and the other sources (`whatsapp_keyword`, `api`, `support`) are
recorded without asking identity; outside header mode `api` and `support` need a service token
(401 without one), since they skip the check. The trust boundary: only a service with
`notification:preferences` reaches the route with a token, so the subject is the web app's server's
word for its signed-in user; identity confirms the consent and the address, not who is at the
browser. A change from the web records the tenant it was made for (`set_for_tenant_id`, migration
0004), which decides which tenant's export shows it.

The recipient, send, notification, bulk and data export routes act for one tenant, checked before the body (a
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
| `POST /bulk` | a user of a CA firm (`ca_admin` or `ca_staff`) whose token names the tenant; no service |
| `GET /data-export` | a user with `owner` or `ca_admin` for their own tenant, or identity's export token: `data:export`, bound to the tenant and addressed to `notification` (a token for another tenant or service, or one naming no tenant, is a 403) |

A caller without the role or scope gets a 403 `auth-forbidden`. The dispatcher reads rule versions
from the rulebook, and a bulk notification reads the clients' obligations from the obligation
service, with the service's own access token once `CW_SERVICE_CLIENT_SECRET` is set (its client is
`notification`, with tenant:act, since the obligations are read for the firm's tenant;
`CW_SERVICE_CLIENT_ID` defaults to it under `make run` and `make worker`); identity refusing the
client is an outage of the rulebook, retried later, or of the obligation service, a 503.
`tests/unit/test_auth_mode.py` covers the three modes.

### A CA firm's bulk change card

`POST /v1/notification/bulk` (`api/bulk.py`, `application/bulk.py`) lets a CA firm tell the clients
a published change affects about it in one request (guide use case 5):

```json
{"rule_version_id": "<the change>", "business_ids": ["<client registration>", "..."],
 "kind": "change_card"}
```

`business_ids` are 1 to 500 businesses, each once: the ones the change's impact lists
(`GET /v1/changes/{rule_version_id}/impact`), the profile nodes the obligations and recipients are
kept for. For each, with no unit of work open, the obligation service lists its open obligations
of the change for the firm's tenant (`CW_OBLIGATION_URL`, `infrastructure/obligation_client.py`);
the card is about the first one due and states its title, steps and due date, as
`obligation.created` would. A business with none is `not_affected`: the change does not apply to
it, asks nothing of it now, or the business is another tenant's, whose obligations row-level
security hides. In one unit of work the cards are then queued through `EnqueueNotifications` with
the route of `obligation.created` (template and occasion `change_card`) for the client's own
people: the recipients that follow the business as an owner or staff. The firm's own people
(`ca_admin`, `ca_staff`) are left out, since they hear about every client in their daily digest.
The change card's dedupe key names the rule version, the business, the channel and the recipient,
so a person who has the card of that change already, from the change itself or an earlier
request, gets nothing more: one card per change, business and person (F9). The cards then go out
like every other, through quiet hours and the batching window.

The answer (201) counts the businesses by outcome, each once: `queued` (at least one person got
the card now), `skipped_duplicate` (everyone who can be reached had it), `skipped_no_recipient`
(no client recipient follows it, or none has an open address) and `skipped_not_affected`, with
`notifications_queued` and each business's outcome, obligation and counts. The same unit of work
writes the audit entry `notification.bulk` of the tenant: the caller (the user a token names, with
their roles, else `system:notification`), the change, and the counts with the businesses by
outcome. The request needs an `Idempotency-Key`: a retry with the same key and body gets the
first answer back for 24 hours (`Idempotent-Replayed: true`), the same key with another body is
422, and a retry while the first runs is 409; keys are kept per tenant in `idempotency_key`
(migration 0003). With `CW_NOTIFICATION_BULK_ENABLED` (flag `notification.bulk`, default off,
owner core-product) off the route answers 503 `notification-bulk-disabled` before it looks at the
key; an obligation service that cannot answer is 503 `notification-dependency-unavailable`, and
the key is released so the retry runs.

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
fails saying the channel is disabled.

### The sink

`CW_NOTIFICATION_CHANNELS` picks what delivers: `real` (the default) wires the two channels as
above, `sink` wires `infrastructure/sink.py` for both, which records each message as one JSON line
in `CW_NOTIFICATION_SINK_PATH` (`var/notification/sink.jsonl`; `make product` uses
`var/product/sink.jsonl`) instead of sending it, and answers with the provider message id
`sink:<dispatch id>`. The settings refuse `sink` unless `CW_ENV` is local or test, so no
deployment runs a channel that reaches nobody; it is configuration like the stores, not a flag
(`NOT_FLAGS` in `infra/scripts/check_flags.py`). Every delivery rule is the dispatcher's or the
consumer's and holds unchanged: consent and suppressions, dedupe by occasion, quiet hours,
batching, digests, retries and fallbacks. WhatsApp's 24-hour window is the adapter's, and the sink
applies it as the Cloud API adapter does: a draft template outside the window is refused with the
same reason (and the email fallback goes at once), inside the window the message goes as free
text, and an email always goes as rendered text. Every template is a draft, and a draft never
reaches a person through the sink either; each line records the template's status, the outcome
(`sent` or `refused` with the reason), the channel, the dispatch and provider message ids, the
address, the language, whether the window was open, and the subject and body. The file is local
(`var/` is git-ignored) and created readable by its owner only, since it holds addresses; the API
process and the worker append to it with one write per line. The inbound side (webhook, keywords, status forwarding)
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
The same migration creates the outbox and the consumer inbox. Migration
`20261006_0003_bulk_idempotency.py` adds py-common's `idempotency_key` (forced row-level security,
plus the purge policy of the daily purge the deployable's worker runs) for the bulk route. Audit
entries go to identity's `audit.event` in the unit of work's transaction
(`py_common.audit.writer`); the memory store keeps them in `MemoryStore.audit`.

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

## Erasure

The worker's consumer of tenant.deletion.requested, group `notification.erasure`, only logs
`erasure.off` while the flag `identity.tenant_erasure` (`CW_TENANT_ERASURE_ENABLED`, per tenant with `CW_TENANT_ERASURE_TENANTS`; off by default) is off for the tenant. On, in the transaction that marks the event
processed (`infrastructure.erasure`), it deletes the tenant's `work_index` entries and
notifications (the delivery receipts are the notification's own times and provider message id),
`recipient_address`, `recipient_business` and `recipient` rows, its `address_directory` rows, its
idempotency keys and its published events. The preferences, which belong to no tenant, follow
this rule: the preference of an address the tenant held (in its directory rows, or set by its
user on the web) is deleted when no other tenant's directory holds the address any more; when
another tenant still holds it, the preference stays, since consent is honoured for every tenant,
and only `set_for_tenant_id` is nulled. Suppressions stay: they hold for every tenant and name
none. It answers tenant.data.erased (service notification) with the row counts and the tables it
kept, and a `tenant.erased` audit row.

## Layout

```
src/notification/
  api/             # router.py (preferences, send, templates, data export), recipients.py, notifications.py, receipts.py,
                   # bulk.py (the public bulk change card), schemas, deps
  application/     # enqueue.py, dispatch.py, send.py (SendNow), fallback.py, receipts.py, email_feedback.py,
                   # resend.py, history.py, recipients.py, preferences.py, retention.py, consent.py, bulk.py,
                   # export.py
  domain/          # notification.py (states and transitions), occasions.py (dedupe keys), routing.py (EVENT_ROUTES),
                   # recipients.py, addresses.py, digest.py, policy.py, receipts.py, channels.py, templates.py,
                   # values.py, preferences.py, repository.py and ports.py (protocols), events.py, errors.py
  infrastructure/  # repository.py and work_index.py (Postgres), memory.py, whatsapp.py, email.py, sink.py,
                   # ses_feedback.py, rulebook_client.py, obligation_client.py, identity_client.py,
                   # events_in.py, metrics.py, models.py
  composition.py   # wire(settings): the use cases on the configured store, channels and rulebook reader
  worker.py        # components(settings): consumer, dispatcher, retention sweep (python -m notification.worker)
  testing.py       # fake channel, clock, rulebook, obligation and consent readers, metrics and SNS, and a
                   # settings builder
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

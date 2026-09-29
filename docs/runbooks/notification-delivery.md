# Notification delivery (NotificationDeliveryFailures, NotificationDuplicateSent, NotificationEmailBounces)

The notification service queues one notification per recipient and occasion, and a dispatcher sends
what is due. It claims due work with a 60-second lease (`WORK_LEASE`), renewed just before each
message goes, checks consent and quiet hours again, gathers what goes to one person and business
into one summary, fills the message with the rule version's facts from the rulebook, and hands it to
the channel. A failed attempt is retried after 60 s and again after 300 s; the third failure fails
the notification and queues a fallback on the recipient's next open address on another channel.
`POST /send` goes through the same queue and dispatcher. A recipient who chose a daily digest, and
every person of a CA firm, gets their notifications held (`digest_pending`) until
`CW_NOTIFICATION_DIGEST_AT` (09:00 IST) and then as one `daily_digest` or `ca_digest`.

The worker (`python -m notification.worker`, locally `make worker SERVICE=notification`) runs the
dispatcher every `CW_NOTIFICATION_DISPATCH_INTERVAL_SECONDS` and consumes the obligation events
in group `notification.obligations`; an event it cannot read goes to
`<topic>.notification.obligations.dlq`. Daily at 03:00 IST it runs the retention sweep, which
deletes notifications older than two years and empties the values of those older than 30 days,
one tenant at a time. Its log says `notification.event_queued` per event,
`notification.dispatched` per run that sent anything and `notification.retention_swept` per
sweep. Three alerts link here:
[NotificationDeliveryFailures](#notificationdeliveryfailures),
[NotificationDuplicateSent](#notificationduplicatesent) and
[NotificationEmailBounces](#notificationemailbounces).

## Metrics

Exported when `CW_OTEL_ENDPOINT` is set (`notification.infrastructure.metrics`):

- `notification_sends_total{channel, outcome}`: one per attempt. `sent`; `retry` (failed,
  another follows); `failed` (the last attempt failed); `suppressed` (the address opted out or
  was suppressed after the notification was queued).
- `notification_delivery_lag_seconds{channel}`: seconds from the moment a notification was due
  to the moment the channel took it. The batching window and quiet hours move that moment, so
  they do not count as delay; a rulebook outage and retries do.
- `notification_duplicate_sent_total{channel}`: deliveries of a notification that was already
  sent.
- `notification_enqueued_total{channel, outcome}`: `queued`, and `duplicate` for an occasion that
  already had its notification (a redelivered event), which is expected.
- `notification_receipts_total{channel, kind, outcome}`: the provider's reports after it took a
  message (`delivered`, `read`, `failed`, ...), forwarded by the WhatsApp bot to
  `POST /v1/notification/receipts/whatsapp`. `applied` moved a notification on; `unchanged` was
  late or repeated; `unknown` names a message no notification carries, which the bot's own
  replies always do. A `failed` receipt fails a sent notification and queues its fallback.

## NotificationDeliveryFailures

More than 1% of the notifications a channel finished over 15 minutes failed for good, for 15
minutes; retries and suppressions are not counted. Severity page; core product owns it. A
customer whose last attempt failed misses the change card or reminder unless the fallback on
another channel reaches them.

1. Which errors: in the database (`make dev-psql` locally, schema `notification`, as a role that
   bypasses row-level security):
   `select channel, error, count(*) from notification where state = 'failed' and failed_at >
   now() - interval '1 hour' group by 1, 2 order by 3 desc`.
2. Read the error:
   - `whatsapp channel disabled`: `CW_WHATSAPP_ENABLED` is off or the Meta credentials are
     missing; see [whatsapp.md](whatsapp.md#manual-steps-before-anything-sends-needs-the-maintainers-accounts).
   - A Graph API status: see [whatsapp.md](whatsapp.md#reminders-are-late-or-not-sent) for what
     each code means.
   - `not rendered: ...`: a template the channel does not have, or a value the message needs and
     the notification does not carry. That is a code or template change; find the template key
     with `select template_key, count(*) from notification where error like 'not rendered%'
     group by 1`.
   - `no channel adapter for ...`: the composition root wired no adapter for the channel.
   - `<channel>: the channel adapter raised <error>`: a bug in the adapter, which raised instead
     of returning a receipt. The worker logs `notification.channel_error` with the traceback and
     the dispatch id. The attempt counts as failed and the rest of the run goes on.
   - `email not built: <error>`: the email library refused a header of the message, so no
     connection was opened. Every attempt fails the same way until the code is fixed; the
     fallback then goes to the recipient's next address.
   - `whatsapp: outside the 24-hour customer service window and template ... is draft, not
     approved`: the person has not written to the business number in the last day, and WhatsApp
     then takes only a template Meta approved. The dispatcher does not retry it and the fallback
     goes at once. Submit the template (see [whatsapp.md](whatsapp.md)) and move its status in
     `notification/domain/templates.py` once Meta approves it.
   - `whatsapp <code>: ...`: Meta reported the failure after it took the message (a receipt).
   - `email channel disabled`: `CW_EMAIL_ENABLED` is off, or `CW_SMTP_HOST` or `CW_EMAIL_FROM`
     is empty; see [Email](#email).
   - `smtp: ...`: the SMTP server refused the login (`535`), the recipient (`recipient refused`)
     or the connection (`ConnectionRefusedError`, `TimeoutError`). Check the SES SMTP
     credentials and that the sending domain is verified in the region.
   - `email bounced: ...` or `email complained: ...`: see
     [NotificationEmailBounces](#notificationemailbounces).
3. Did the fallback go: `select channel, state, count(*) from notification where fallback_of is
   not null and created_at > now() - interval '1 hour' group by 1, 2`.

Fix the cause first: a token, a flag, a template. Nothing sends a failed notification again on
its own: once the cause is fixed, `POST /v1/notification/notifications/{id}/resend` (with the
tenant's `x-tenant-id`) queues one again, and `GET /v1/notification/notifications?business_id=`
lists a business's notifications with their state. If a change card or a reminder was lost for
a business, support tells its owner.

## NotificationDuplicateSent

A notification was delivered twice. The dispatcher renews its 60-second lease on a message's
notifications just before it sends that message, and sends nothing whose lease another worker
took. So this happens only when one delivery outlasted the whole lease, because a channel call
hung past its client timeout or the process stalled, and another dispatcher sent the message
meanwhile; the first one's delivery is then counted here and not recorded. Severity page; core
product owns it. The person got the same message twice.

1. Which channel, and when: `sum by (channel) (increase(notification_duplicate_sent_total[1h]))`.
2. Look for slow deliveries at that time: the dispatcher's log lines and the channel's HTTP spans
   in Tempo. The WhatsApp adapter waits up to 30 seconds for the Graph API.
3. A process that stalled (CPU starvation, a long pause) shows as a gap in its logs.

Fix: a channel that answers slowly needs a shorter client timeout than the lease; a lease that is
too short for one delivery on a healthy channel is `WORK_LEASE` in
`notification/domain/policy.py`. Tell support which business got the duplicate so they can
apologise if it asks.

## NotificationEmailBounces

Bounces and complaints that SES reported against email notifications passed 2% of the email
notifications sent over 6 hours, for 30 minutes. Severity ticket; core product owns it. SES puts
the sending account under review at 5% bounces or 0.1% complaints, and may then stop it from
sending. Each permanent bounce and each complaint has already suppressed its mailbox for every
tenant, so the same address is not written to again.

1. Which kind: `sum by (kind) (increase(notification_receipts_total{channel="email"}[6h]))`.
2. Which mailboxes: `select reason, detail, count(*) from suppression where channel = 'email'
   and created_at > now() - interval '6 hours' group by 1, 2`.
3. Bounces from one business or onboarding path usually mean addresses typed wrong at sign-up;
   complaints mean people who did not expect the mail. Tell core product which.

A suppression holds until support lifts it, once the person confirms the address:
`delete from suppression where channel = 'email' and address = '<address>'` (the address in
lower case). The notifications that were suppressed meanwhile are not sent again.

## Email

Email goes out over SMTP (SES's SMTP interface) only with `CW_EMAIL_ENABLED=true` (the
`notification.email` flag, off by default), `CW_SMTP_HOST`, `CW_SMTP_PORT` (587),
`CW_SMTP_USERNAME`, `CW_SMTP_PASSWORD` and `CW_EMAIL_FROM`. The connection needs STARTTLS.
Every message carries its dispatch id in the `X-CW-Dispatch-Id` header, and SES's reports
match a message by it.

SES feedback, once per environment (manual, in the AWS console):

1. Create an SES configuration set, make it the default for the sending identity, and add an
   event destination to an SNS topic for bounces, complaints and deliveries, with the original
   headers included (without them a report still suppresses its mailbox but cannot find its
   notification).
2. Generate a secret, set it as `CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN`, and set the topic's ARN
   as `CW_NOTIFICATION_SES_TOPIC_ARN`.
3. Subscribe `https://sns:<secret>@<api-host>/v1/notification/receipts/email` to the topic
   (HTTPS). The secret travels as HTTP basic credentials, never in the path that logs and
   spans record.
4. The service logs `notification.ses_subscription_pending` with the `subscribe_url`; open that
   URL once to confirm the subscription.

The route answers 503 while the secret is unset, 401 without the credentials, and 422 for a
body that is not an SNS message signed with SHA-256 (`SignatureVersion` 2) by a certificate on
`sns.<region>.amazonaws.com`, or that comes from another topic. A 503 with `SNS signing
certificate` in its detail means the certificate could not be fetched; SNS retries.

# Notification delivery (NotificationDeliveryFailures, NotificationDuplicateSent)

The notification service queues one notification per recipient and occasion, and a dispatcher
sends what is due. It claims due work with a 60-second lease (`WORK_LEASE`), checks consent and
quiet hours again, gathers what goes to one person and business into one summary, fills the
message with the rule version's facts from the rulebook, and hands it to the channel. A failed
attempt is retried after 60 s and again after 300 s; the third failure fails the notification
and queues a fallback on the recipient's next open address on another channel. `POST /send`
goes through the same queue and dispatcher.

The worker (`python -m notification.worker`, locally `make worker SERVICE=notification`) runs the
dispatcher every `CW_NOTIFICATION_DISPATCH_INTERVAL_SECONDS` and consumes the obligation events
in group `notification.obligations`; an event it cannot read goes to
`<topic>.notification.obligations.dlq`. Its log says `notification.event_queued` per event and
`notification.dispatched` per run that sent anything. Two alerts link here:
[NotificationDeliveryFailures](#notificationdeliveryfailures) and
[NotificationDuplicateSent](#notificationduplicatesent).

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
3. Did the fallback go: `select channel, state, count(*) from notification where fallback_of is
   not null and created_at > now() - interval '1 hour' group by 1, 2`.

Fix the cause first: a token, a flag, a template. Nothing sends a failed notification again on
its own. If a change card or a reminder was lost for a business, support tells its owner.

## NotificationDuplicateSent

A notification was delivered twice. That happens only when a dispatcher held a claimed
notification past its 60-second lease, because a channel call hung or the process stalled, and
another dispatcher sent it meanwhile; the first one's delivery is then counted here and not
recorded. Severity page; core product owns it. The person got the same message twice.

1. Which channel, and when: `sum by (channel) (increase(notification_duplicate_sent_total[1h]))`.
2. Look for slow deliveries at that time: the dispatcher's log lines and the channel's HTTP spans
   in Tempo. The WhatsApp adapter waits up to 30 seconds for the Graph API.
3. A process that stalled (CPU starvation, a long pause) shows as a gap in its logs.

Fix: a channel that answers slowly needs a shorter client timeout than the lease; a lease that is
too short for a healthy channel is `WORK_LEASE` in `notification/domain/policy.py`. Tell support
which business got the duplicate so they can apologise if it asks.

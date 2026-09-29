# WhatsApp bot and channel

Design reference: guide sections 7 (F9 notifications), 16 (privacy) and 18. Code:
`apps/whatsapp-bot` (inbound webhook, TypeScript) and `services/notification` (outbound
channel, preferences, templates, Python).

## Manual steps before anything sends (needs the maintainer's accounts)

1. Meta Business account and a WhatsApp Business app in the Meta developer dashboard; a phone
   number (or the test number) attached to the app. Note the **phone number id** and create a
   **system user access token** with `whatsapp_business_messaging`.
2. Webhook: in the app dashboard set the callback URL to the bot's `/webhook`, choose a
   **verify token** and paste the **app secret**. The bot checks both
   (`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`). Subscribe to the `messages` field.
3. Submit the message templates in `services/notification/src/notification/domain/templates.py`
   (`meta_name` values) for approval under the utility category: `cw_obligation_due_soon_*`,
   `cw_obligation_created_*`, `cw_change_card_*`, `cw_obligation_closed_*`,
   `cw_obligation_deadline_extended_*`, `cw_obligation_corrected_*`,
   `cw_obligation_withdrawn_*`, `cw_batch_summary_*`, `cw_daily_digest_*` and `cw_ca_digest_*`,
   each in English (`_en`) and Hindi (`_hi`). The Hindi copy needs an analyst's review first;
   decide whether the pilot needs it at all. Set each template's `status` in code to
   `submitted`, then `approved`, as Meta answers. Until a template is approved, its message
   goes out only to a number that wrote to the business in the last 24 hours (see
   [the 24-hour window](#delivery-statuses-and-the-24-hour-window)); to anyone else it fails at
   once and falls back to email.
4. Flip the flags: bot `WHATSAPP_SEND_ENABLED=true` with `WHATSAPP_PHONE_NUMBER_ID` and
   `WHATSAPP_ACCESS_TOKEN`; notification service `CW_WHATSAPP_ENABLED=true` with
   `CW_WHATSAPP_PHONE_NUMBER_ID` and `CW_WHATSAPP_ACCESS_TOKEN`. Until then the bot logs the
   reply it would send and the channel returns a failed receipt saying it is disabled.
5. Legal: the privacy notice and the WhatsApp consent wording in `docs/legal` must be reviewed
   before the opt-in checkbox goes live.
6. Consent recording, once the lawyer has confirmed that a keyword opt-in is valid consent
   (`docs/legal/README.md`) and identity runs in the deployed profile: set the same secret as
   `CW_IDENTITY_CHANNEL_TOKEN` on identity and `IDENTITY_SERVICE_TOKEN` on the bot, point
   `IDENTITY_API_URL` at identity, and set `WHATSAPP_CONSENT_RECORDING_ENABLED=true` on the bot.
7. Delivery statuses: generate one shared secret and set it as `CW_NOTIFICATION_BOT_TOKEN` on
   the notification service and `NOTIFICATION_BOT_TOKEN` on the bot, with the bot's
   `NOTIFICATION_API_URL` pointing at notification. Without it the bot forwards nothing and
   warns once at start: notification then never sees a message delivered or read, and treats
   every number as outside the 24-hour window.
8. Service token, needed once notification and identity run `CW_AUTH_MODE=token` (they then
   refuse the two shared tokens of steps 6 and 7): create the bot's client at identity with
   `identity-admin service-client create --id whatsapp-bot --scope notification:preferences
   --scope notification:receipts --scope identity:channel-consents --scope tenant:act`, and set
   `BOT_SERVICE_CLIENT_ID` and `BOT_SERVICE_CLIENT_SECRET` on the bot with `IDENTITY_API_URL`
   pointing at identity. The bot then sends its access token on every call, and the shared tokens
   too while they are set, so it works in every mode (`apps/whatsapp-bot/README.md`). Rotating any
   of these values: `docs/runbooks/secret-rotation.md`.

## Consent recording (`WHATSAPP_CONSENT_RECORDING_ENABLED`)

With the flag on, every START and STOP is recorded as a channel consent in identity
(`POST /v1/identity/channel-consents`, `docs/legal/consent-record.md`). The flag is off by
default (owner core-product); off, the bot logs `consent recording disabled; would record ...`
and behaves as before. It is removed, and recording made unconditional, once the lawyer
confirms the keyword opt-in wording and identity runs in the deployed profile.

- **The bot will not start**, with `WHATSAPP_CONSENT_RECORDING_ENABLED=true needs
  IDENTITY_SERVICE_TOKEN or BOT_SERVICE_CLIENT_SECRET`: the flag is on and the bot has neither
  the shared token nor a service client. Set the token (the value of identity's
  `CW_IDENTITY_CHANNEL_TOKEN`) or the client secret (manual step 8), or turn the flag off. The
  bot refuses to start rather than switch reminders on without a record.
- **Opt-ins fail closed while identity is down.** An opt-in is recorded first and switched on
  only once the record exists. When the call fails, the person gets the "try again later" reply,
  the log says `opt-in of ****1234 not recorded, so not applied` with the status (`consents: 503`
  when identity has no `CW_IDENTITY_CHANNEL_TOKEN`, `consents: 401` for a token that differs from
  the bot's, or when identity runs in token mode and the bot has no service token; `consents: 403`
  when the bot's client lacks `identity:channel-consents`), and no preference is set. Nothing to replay: the person sends START again once
  identity answers.
- **Opt-outs never wait for identity.** The preference is set first; the withdrawal is recorded
  afterwards on a best-effort basis, and a failure is logged as `opt-out of ****1234 honoured but
  not recorded`. The person is opted out either way (the notification preference and its
  `updated_at` are the record of it); only the channel consent history misses that withdrawal,
  and the log masks the number, so note the incident rather than guess the number.
- A number's recorded history: `GET /v1/identity/channel-consents/whatsapp/<number>` with the
  shared token in `x-cw-service-token`, or in token mode with an access token of a client holding
  `identity:channel-consents`.
- A redelivered webhook is harmless: the message id finds the first record and identity answers
  200 with it.

## Webhook returns 401

The signature did not verify. Check the app secret matches the dashboard, that the proxy
passes the raw body unchanged (no re-encoding, no trailing newline) and the
`X-Hub-Signature-256` header. Meta retries a non-2xx delivery with backoff for a while, so a
short outage loses nothing; a long one does.

## Meta's handshake fails (403 on GET /webhook)

`hub.verify_token` does not equal `WHATSAPP_VERIFY_TOKEN`, or the token is empty (an empty
token never verifies, by design).

## A person says they opted out and still got a message

1. `GET /v1/notification/preferences/whatsapp/<number>` shows the current preference and its
   `updated_at`; an opt-out is honoured from that moment.
2. Check the bot log for the inbound STOP: was it delivered, and did the preference call
   succeed (a failed PUT throws and Meta retries the delivery)?
3. Find the message: `GET /v1/notification/notifications?business_id=<id>` (with the tenant's
   `x-tenant-id`) lists the business's notifications with the address, state and `sent_at`.
   Consent is checked when a notification is queued and again when it goes out, so one sent
   before the opt-out's `updated_at` was allowed; one sent after it is a bug to report to core
   product.
4. Reply to the person from the business number with the opt-out confirmation and record a
   support opt-out (`source: support`).

## Reminders are late or not sent

- `deferred` outcomes mean quiet hours (default 21:00 to 08:00 IST); the notification stays
  queued and the service's dispatcher sends it at `scheduled_for`.
- Batching and digests delay on purpose: a notification waits up to
  `CW_NOTIFICATION_BATCH_WINDOW_SECONDS` (300) for others to the same person, and a recipient
  with a daily digest, or anyone at a CA firm, hears at `CW_NOTIFICATION_DIGEST_AT` (09:00 IST).
- Nothing is dispatched at all: the notification worker (`python -m notification.worker`) is
  not running; its log says `notification.dispatched` for every run that sent something.
- `failed` with "channel disabled": the flag is off (see the manual steps).
- `failed` with "outside the 24-hour customer service window": the number has not written to
  the business in the last day and the template is not approved yet (manual step 3). The
  email fallback goes at once when the recipient has an open email address.
- `failed` with a Graph API status: 401 means an expired token, 400 with error 131047 means
  the 24-hour window closed and a template is required, 131026 means the number is not on
  WhatsApp, 130429 means rate limits. The service retries after 60 and 300 seconds; after the
  third failure it queues the fallback on the recipient's next open address (email, with
  `CW_EMAIL_ENABLED`), and the obligation stays visible in the web app.
  [notification-delivery.md](notification-delivery.md) has the queries and the alerts.
- A drop in Meta's quality rating limits the number of business-initiated conversations;
  the dashboard shows it. Too many opt-outs or blocks lower it: check the template wording.

## Delivery statuses and the 24-hour window

The bot forwards every webhook delivery's statuses and the times numbers wrote to the business
to `POST /v1/notification/receipts/whatsapp` before it handles any message. A number that wrote
in the last 24 hours gets free text; anyone else only an approved template.

- **The bot answers 500 to Meta** and its log says `... not forwarded to notification, so
  nothing was handled: Error: receipts: <status>`. `401`: the two tokens differ (manual step
  7). `503`: notification has no `CW_NOTIFICATION_BOT_TOKEN`. A connection error: notification
  is down. Meta delivers the webhook again with backoff, and no reply goes out until the
  forward succeeds, so a short outage loses nothing.
- **Statuses counted as `unknown`** (`notification_receipts_total{outcome="unknown"}`) are the
  bot's own replies, which notification did not send; that is expected.
- **A status arrived but the notification did not move**: a status only moves a notification
  forward (sent, delivered, read), so a late `delivered` after `read` changes nothing and is
  counted `unchanged`.

## Templates rejected

Meta rejects templates that read as marketing or have variables without context. Keep every
reminder factual, name the business and the due date, and end with the HELP/STOP line.

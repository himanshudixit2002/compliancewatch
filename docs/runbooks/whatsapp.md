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
   (`meta_name` values) for approval under the utility category; set their `status` in code
   to `submitted`, then `approved`, as Meta answers. Reminders cannot leave until approval.
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

## Consent recording (`WHATSAPP_CONSENT_RECORDING_ENABLED`)

With the flag on, every START and STOP is recorded as a channel consent in identity
(`POST /v1/identity/channel-consents`, `docs/legal/consent-record.md`). The flag is off by
default (owner core-product); off, the bot logs `consent recording disabled; would record ...`
and behaves as before. It is removed, and recording made unconditional, once the lawyer
confirms the keyword opt-in wording and identity runs in the deployed profile.

- **The bot will not start**, with `WHATSAPP_CONSENT_RECORDING_ENABLED=true needs
  IDENTITY_SERVICE_TOKEN`: the flag is on and the token is empty. Set the token (the value of
  identity's `CW_IDENTITY_CHANNEL_TOKEN`) or turn the flag off. The bot refuses to start rather
  than switch reminders on without a record.
- **Opt-ins fail closed while identity is down.** An opt-in is recorded first and switched on
  only once the record exists. When the call fails, the person gets the "try again later" reply,
  the log says `opt-in of ****1234 not recorded, so not applied` with the status (`consents: 503`
  when identity has no `CW_IDENTITY_CHANNEL_TOKEN`, `consents: 401` for a token that differs from
  the bot's), and no preference is set. Nothing to replay: the person sends START again once
  identity answers.
- **Opt-outs never wait for identity.** The preference is set first; the withdrawal is recorded
  afterwards on a best-effort basis, and a failure is logged as `opt-out of ****1234 honoured but
  not recorded`. The person is opted out either way (the notification preference and its
  `updated_at` are the record of it); only the channel consent history misses that withdrawal,
  and the log masks the number, so note the incident rather than guess the number.
- A number's recorded history: `GET /v1/identity/channel-consents/whatsapp/<number>` with the
  service token in `x-cw-service-token`.
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
3. Check the sent log for the dedupe key of the message; the send use case refuses
   `not_opted_in` before rendering.
4. Reply to the person from the business number with the opt-out confirmation and record a
   support opt-out (`source: support`).

## Reminders are late or not sent

- `deferred` outcomes mean quiet hours (default 21:00 to 08:00 IST); the scheduler retries at
  `scheduled_for`.
- `failed` with "channel disabled": the flag is off (see the manual steps).
- `failed` with a Graph API status: 401 means an expired token, 400 with error 131047 means
  the 24-hour window closed and a template is required, 131026 means the number is not on
  WhatsApp, 130429 means rate limits. The retry policy is three attempts; after that the
  obligation stays visible in the web app and the email channel is the fallback once wired.
- A drop in Meta's quality rating limits the number of business-initiated conversations;
  the dashboard shows it. Too many opt-outs or blocks lower it: check the template wording.

## Templates rejected

Meta rejects templates that read as marketing or have variables without context. Keep every
reminder factual, name the business and the due date, and end with the HELP/STOP line.

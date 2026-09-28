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

# whatsapp-bot app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7, 12 and 14.

- **Owns:** Webhook receiver and conversation state for the WhatsApp Business Cloud API (TypeScript)
- **Owning team:** Core Product (guide section 14)
- **Consumes:** WhatsApp Business Cloud API webhooks; qa API; public REST API v1
- **Emits / publishes:** n/a (calls product APIs: notification's preferences and receipts, identity's channel consents)

## Layout

```
src/app.ts           # Hono app: GET /health, GET /webhook (handshake with the verify token), POST /webhook (signature, parse, forward receipts, converse)
src/signature.ts     # X-Hub-Signature-256: HMAC-SHA256 of the raw body, constant-time compare
src/webhook.ts       # Cloud API payload -> InboundMessage / StatusUpdate (anti-corruption layer)
src/receipts.ts      # statuses and inbound times of a delivery, as notification's receipt route takes them
src/consent.ts       # STOP / START / HELP keywords in English, Hindi and Hinglish; language detection
src/conversation.ts  # one message in, one reply out; opt-out first, opt-in prompt for strangers; keywords recorded as consents
src/replies.ts       # session replies (en, hi); reminders are rendered by the notification service
src/clients.ts       # preferences and receipts clients (notification service), consent ledger (identity service), Cloud API sender, logging sender, qa stub
src/auth.ts          # IdentityTokenSource: the bot's service token from identity (client credentials, cached); authorizedFetch
src/index.ts         # bootstrap; sending is off unless WHATSAPP_SEND_ENABLED=true with credentials
src/contracts.test.ts  # the recorded calls to notification and identity (packages/contracts/consumers/whatsapp-bot)
```

## Service token

With `BOT_SERVICE_CLIENT_SECRET` set, the bot exchanges `BOT_SERVICE_CLIENT_ID` (by default
`whatsapp-bot`) and the secret at identity's `POST /v1/identity/service-tokens`
(`IDENTITY_API_URL`) and sends the access token it gets as `Authorization: Bearer` on every call to
notification (preferences and receipts) and identity (channel consents). The token is kept until
a minute before it expires, so identity is asked about every nine minutes; when a service refuses
the token itself (401 with an `invalid_token` challenge or the `auth-token-invalid` problem type)
the bot fetches a new token and sends the request once more, and any other 401 comes back as it
came. The client needs the scopes
notification:preferences, notification:receipts and identity:channel-consents; locally identity
creates it from `services/identity/src/identity/identity_dev_clients.toml` when its
`CW_IDENTITY_DEV_CLIENT_SECRET` is set, and the bot's secret is that same value. Elsewhere it is
created with `identity-admin service-client create`, which prints the secret once.

The shared tokens (`NOTIFICATION_BOT_TOKEN`, `IDENTITY_SERVICE_TOKEN`) still go out while they are
set, so one bot works against services in `header` mode (which read the shared tokens), `dual`
mode (the bearer when one is sent) and `token` mode (the bearer alone). Without the client secret
no token is sent and the bot behaves as before. When identity cannot issue a token, the call that
needed it fails: a preference change is answered with the try-again reply, and a receipts forward
answers the webhook with a 500 so Meta delivers it again.

## Consent recording

With `WHATSAPP_CONSENT_RECORDING_ENABLED=true` every START and STOP becomes a channel consent in
the identity service (`POST /v1/identity/channel-consents` with `IDENTITY_SERVICE_TOKEN`, the
same value as identity's `CW_IDENTITY_CHANNEL_TOKEN`): the number, the keyword, the message id,
the time, the language and the notice version (`WHATSAPP_NOTICE_VERSION`, by default the
version line of `docs/legal/whatsapp-consent.md`). An opt-in is recorded first and switched on
only once the record exists; when identity cannot record it the person is asked to try again
later and nothing is switched on. An opt-out is honoured first, always, and recording the
withdrawal is best effort (a failure is logged with the number masked). The flag is off by
default (owner core-product); off, the bot logs what it would record and behaves as before. It
is removed, and recording made unconditional, once the lawyer confirms the keyword opt-in
wording (the open question in `docs/legal/README.md`) and identity runs in the deployed
profile. On, the bot refuses to start without `IDENTITY_SERVICE_TOKEN` or the service token.

## Delivery statuses and inbound times

Every webhook delivery's statuses (sent, delivered, read, failed, with Meta's error code and
title) and the time each number wrote to the business go to notification's
`POST /v1/notification/receipts/whatsapp` with `NOTIFICATION_BOT_TOKEN` (the same value as
notification's `CW_NOTIFICATION_BOT_TOKEN`), before any message is handled. The statuses tell
notification what became of the reminders it sent; the inbound times open WhatsApp's 24-hour
window, inside which it may send free text instead of an approved template. When the forward
fails the delivery is answered with a 500 and no reply goes out, so Meta delivers it again.
Without the token or the service token nothing is forwarded and the bot warns once at start.
What each forwarding failure means is in `docs/runbooks/whatsapp.md` (delivery statuses and the
24-hour window).

The calls the bot makes to notification and identity are recorded in
`packages/contracts/consumers/whatsapp-bot/`: `contracts.test.ts` checks the clients send
exactly those requests, and each provider's `tests/contract/test_consumers.py` replays them.

## How to run

`pnpm --filter whatsapp-bot dev` (Node 22+ runs the TypeScript source directly), `build` then `start`, `test`. Copy `.env.example` to `.env`: `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` (both checked; an empty verify token never verifies), `WHATSAPP_REQUIRE_SIGNATURE` (false only locally), `WHATSAPP_SEND_ENABLED` with `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_ACCESS_TOKEN` (replies leave the process only then), `NOTIFICATION_API_URL` and `NOTIFICATION_BOT_TOKEN`, the service client (`BOT_SERVICE_CLIENT_ID`, `BOT_SERVICE_CLIENT_SECRET` and `IDENTITY_API_URL`), and for consent recording `WHATSAPP_CONSENT_RECORDING_ENABLED`, `IDENTITY_API_URL`, `IDENTITY_SERVICE_TOKEN` and `WHATSAPP_NOTICE_VERSION`. The manual steps on the Meta side and the failure modes are in `docs/runbooks/whatsapp.md`; the consent wording in `docs/legal/whatsapp-consent.md`.

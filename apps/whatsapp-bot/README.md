# whatsapp-bot app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7, 12 and 14.

- **Owns:** Webhook receiver and conversation state for the WhatsApp Business Cloud API (TypeScript)
- **Owning team:** Core Product (guide section 14)
- **Consumes:** WhatsApp Business Cloud API webhooks; qa API; public REST API v1
- **Emits / publishes:** n/a (calls product APIs)

## Layout

```
src/app.ts           # Hono app: GET /health, GET /webhook (handshake with the verify token), POST /webhook (signature, parse, converse)
src/signature.ts     # X-Hub-Signature-256: HMAC-SHA256 of the raw body, constant-time compare
src/webhook.ts       # Cloud API payload -> InboundMessage / StatusUpdate (anti-corruption layer)
src/consent.ts       # STOP / START / HELP keywords in English, Hindi and Hinglish; language detection
src/conversation.ts  # one message in, one reply out; opt-out first, opt-in prompt for strangers
src/replies.ts       # session replies (en, hi); reminders are rendered by the notification service
src/clients.ts       # preferences client (notification service), Cloud API sender, logging sender, qa stub
src/index.ts         # bootstrap; sending is off unless WHATSAPP_SEND_ENABLED=true with credentials
```

## How to run

`pnpm --filter whatsapp-bot dev` (Node 22+ runs the TypeScript source directly), `build` then `start`, `test`. Copy `.env.example` to `.env`: `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` (both checked; an empty verify token never verifies), `WHATSAPP_REQUIRE_SIGNATURE` (false only locally), `WHATSAPP_SEND_ENABLED` with `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_ACCESS_TOKEN` (replies leave the process only then), `NOTIFICATION_API_URL`. The manual steps on the Meta side and the failure modes are in `docs/runbooks/whatsapp.md`; the consent wording in `docs/legal/whatsapp-consent.md`.

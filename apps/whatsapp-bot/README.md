# whatsapp-bot app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7, 12 and 14.

- **Owns:** Webhook receiver and conversation state for the WhatsApp Business Cloud API (TypeScript)
- **Owning team:** Core Product (guide section 14)
- **Consumes:** WhatsApp Business Cloud API webhooks; qa API; public REST API v1
- **Emits / publishes:** n/a (calls product APIs)

## Layout

```
src/app.ts        # Hono app: GET /health, GET /webhook (Meta handshake), POST /webhook (stub)
src/index.ts      # @hono/node-server bootstrap, PORT (default 8080)
src/app.test.ts   # vitest via app.request(), 80% coverage thresholds
```

## How to run

`pnpm --filter whatsapp-bot dev` (Node 22+ runs the TypeScript source directly), `build` then `start`, `test`. Copy `.env.example` to `.env` for `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` (signature verification is still a TODO).

import { Hono } from "hono";

/**
 * HTTP surface of the WhatsApp webhook receiver (guide section 7).
 * Free of server bootstrap so tests can call `app.request()` directly.
 */
export const app = new Hono();

app.get("/health", (c) => c.json({ status: "ok", service: "whatsapp-bot" }));

// Meta verification handshake: GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
app.get("/webhook", (c) => {
  const mode = c.req.query("hub.mode");
  const challenge = c.req.query("hub.challenge");
  // TODO(phase 1): reject unless hub.verify_token === WHATSAPP_VERIFY_TOKEN.
  if (mode === "subscribe" && challenge !== undefined) {
    return c.text(challenge, 200);
  }
  return c.text("Bad Request", 400);
});

// Inbound messages and status updates. Stub: acknowledges everything.
app.post("/webhook", async (c) => {
  // TODO(phase 1): verify X-Hub-Signature-256 (HMAC-SHA256 of the raw body with WHATSAPP_APP_SECRET)
  // before parsing, then hand the payload to the conversation state machine.
  await c.req.text();
  return c.json({ received: true }, 200);
});

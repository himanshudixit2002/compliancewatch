import { Hono } from "hono";
import type { Deps } from "./conversation.ts";
import { handleInbound } from "./conversation.ts";
import type { ReceiptsClient } from "./receipts.ts";
import { isEmpty, receiptsOf } from "./receipts.ts";
import { verifySignature } from "./signature.ts";
import { parseWebhook } from "./webhook.ts";

export interface AppConfig {
  readonly verifyToken: string;
  readonly appSecret: string;
  /** Reject unsigned deliveries. Off only for local runs without an app secret. */
  readonly requireSignature: boolean;
}

/**
 * HTTP surface of the WhatsApp webhook receiver (guide section 7).
 * Free of server bootstrap so tests can call `app.request()` directly.
 *
 * Before any message is handled, the delivery's statuses and the times numbers wrote to us go to
 * the notification service (`receipts`). When that fails the delivery is answered with a 500 and
 * nothing is handled or replied to: Meta delivers the webhook again, and the statuses and
 * replies go then, once each.
 */
export function createApp(config: AppConfig, deps: Deps, receipts?: ReceiptsClient): Hono {
  const app = new Hono();

  app.get("/health", (c) => c.json({ status: "ok", service: "whatsapp-bot" }));

  // Meta verification handshake: GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
  app.get("/webhook", (c) => {
    const mode = c.req.query("hub.mode");
    const token = c.req.query("hub.verify_token");
    const challenge = c.req.query("hub.challenge");
    if (
      mode === "subscribe" &&
      challenge !== undefined &&
      config.verifyToken !== "" &&
      token === config.verifyToken
    ) {
      return c.text(challenge, 200);
    }
    return c.text("Forbidden", 403);
  });

  // Inbound messages and status updates. The signature is checked on the raw body before parsing.
  app.post("/webhook", async (c) => {
    const raw = await c.req.text();
    const signature = c.req.header("x-hub-signature-256");
    if (config.requireSignature && !verifySignature(raw, signature, config.appSecret)) {
      return c.json({ error: "invalid signature" }, 401);
    }
    let payload: unknown;
    try {
      payload = JSON.parse(raw);
    } catch {
      return c.json({ error: "invalid json" }, 400);
    }
    const parsed = parseWebhook(payload);
    const reports = receiptsOf(parsed);
    if (receipts !== undefined && !isEmpty(reports)) {
      try {
        await receipts.forward(reports);
      } catch (error) {
        (deps.log ?? console.error)(
          `whatsapp-bot: ${reports.statuses.length} statuses and ${reports.inbound.length} inbound times not forwarded to notification, so nothing was handled: ${String(error)}`,
        );
        return c.json({ error: "forwarding to notification failed" }, 500);
      }
    }
    const handled = [];
    for (const message of parsed.messages) {
      handled.push(await handleInbound(message, deps));
    }
    // Meta retries on anything but a 2xx; the reply is best effort and never blocks the ack.
    return c.json(
      { received: true, messages: handled.length, statuses: parsed.statuses.length },
      200,
    );
  });

  return app;
}

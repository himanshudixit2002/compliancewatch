import { describe, expect, it } from "vitest";
import { app } from "./app.ts";

describe("whatsapp-bot http surface", () => {
  it("GET /health reports ok", async () => {
    const res = await app.request("/health");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok", service: "whatsapp-bot" });
  });

  it("GET /webhook echoes the Meta verification challenge", async () => {
    const res = await app.request(
      "/webhook?hub.mode=subscribe&hub.verify_token=x&hub.challenge=12345",
    );
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("12345");
  });

  it("GET /webhook without a subscribe handshake is rejected", async () => {
    const res = await app.request("/webhook");
    expect(res.status).toBe(400);
  });

  it("POST /webhook acknowledges any payload (signature check is a TODO)", async () => {
    const res = await app.request("/webhook", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ object: "whatsapp_business_account", entry: [] }),
    });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ received: true });
  });
});

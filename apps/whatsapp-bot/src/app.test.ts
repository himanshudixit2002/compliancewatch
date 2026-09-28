import { describe, expect, it } from "vitest";
import { createApp } from "./app.ts";
import type { Deps } from "./conversation.ts";
import { signBody } from "./signature.ts";

const SECRET = "test-app-secret";

function fakeDeps() {
  const optIns = new Map<string, boolean>();
  const sent: Array<{ to: string; body: string }> = [];
  const deps: Deps = {
    preferences: {
      async setOptIn(phone, optedIn) {
        optIns.set(phone, optedIn);
      },
      async isOptedIn(phone) {
        return optIns.get(phone) === true;
      },
    },
    sender: {
      async sendText(to, body) {
        sent.push({ to, body });
      },
    },
    qa: {
      async ask() {
        return null;
      },
    },
  };
  return { deps, optIns, sent };
}

function inbound(text: string, from = "919876543210") {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "1",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "1", phone_number_id: "42" },
              messages: [
                { from, id: "wamid.1", timestamp: "1", type: "text", text: { body: text } },
              ],
            },
          },
        ],
      },
    ],
  };
}

function build(requireSignature = true) {
  const fakes = fakeDeps();
  const app = createApp(
    { verifyToken: "verify-me", appSecret: SECRET, requireSignature },
    fakes.deps,
  );
  return { app, ...fakes };
}

async function post(app: ReturnType<typeof createApp>, payload: unknown, sign = true) {
  const raw = JSON.stringify(payload);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (sign) headers["x-hub-signature-256"] = signBody(raw, SECRET);
  return app.request("/webhook", { method: "POST", headers, body: raw });
}

describe("whatsapp-bot http surface", () => {
  it("GET /health reports ok", async () => {
    const { app } = build();
    const res = await app.request("/health");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok", service: "whatsapp-bot" });
  });

  it("GET /webhook echoes the challenge only with the right verify token", async () => {
    const { app } = build();
    const ok = await app.request(
      "/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345",
    );
    expect(ok.status).toBe(200);
    expect(await ok.text()).toBe("12345");
    const wrong = await app.request(
      "/webhook?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=12345",
    );
    expect(wrong.status).toBe(403);
    const bare = await app.request("/webhook");
    expect(bare.status).toBe(403);
  });

  it("POST /webhook rejects a missing or wrong signature", async () => {
    const { app } = build();
    const unsigned = await post(app, inbound("hi"), false);
    expect(unsigned.status).toBe(401);
    const tampered = await app.request("/webhook", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-hub-signature-256": "sha256=" + "0".repeat(64),
      },
      body: JSON.stringify(inbound("hi")),
    });
    expect(tampered.status).toBe(401);
  });

  it("POST /webhook rejects bad json but acknowledges unknown objects", async () => {
    const { app } = build();
    const bad = await app.request("/webhook", {
      method: "POST",
      headers: { "x-hub-signature-256": signBody("{", SECRET) },
      body: "{",
    });
    expect(bad.status).toBe(400);
    const other = await post(app, { object: "page" });
    expect(other.status).toBe(200);
    expect(await other.json()).toEqual({ received: true, messages: 0, statuses: 0 });
  });

  it("STOP records an opt-out and replies; START opts back in", async () => {
    const { app, optIns, sent } = build();
    const res = await post(app, inbound("Stop."));
    expect(res.status).toBe(200);
    expect(optIns.get("919876543210")).toBe(false);
    expect(sent[0]?.body).toContain("Reply START");
    await post(app, inbound("शुरू"));
    expect(optIns.get("919876543210")).toBe(true);
    expect(sent[1]?.body).toContain("STOP");
    expect(/[ऀ-ॿ]/.test(sent[1]?.body ?? "")).toBe(true);
  });

  it("a question before opting in gets the opt-in prompt, after it the not-connected reply", async () => {
    const { app, sent } = build();
    await post(app, inbound("When is GSTR-3B due?"));
    expect(sent[0]?.body).toContain("Reply START");
    await post(app, inbound("START"));
    await post(app, inbound("When is GSTR-3B due?"));
    expect(sent[2]?.body).toContain("not answered on WhatsApp yet");
    const help = await post(app, inbound("HELP"));
    expect(help.status).toBe(200);
    expect(sent[3]?.body).toContain("Reply START to receive them");
  });

  it("status updates are counted, not handled", async () => {
    const { app, sent } = build();
    const payload = {
      object: "whatsapp_business_account",
      entry: [
        {
          changes: [
            {
              value: {
                statuses: [
                  { id: "wamid.1", recipient_id: "9", status: "delivered", timestamp: "1" },
                ],
              },
            },
          ],
        },
      ],
    };
    const res = await post(app, payload);
    expect(await res.json()).toEqual({ received: true, messages: 0, statuses: 1 });
    expect(sent).toHaveLength(0);
  });

  it("signature can be switched off for local runs", async () => {
    const { app } = build(false);
    const res = await post(app, inbound("HELP"), false);
    expect(res.status).toBe(200);
  });
});

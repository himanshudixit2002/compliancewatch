import { describe, expect, it, vi } from "vitest";
import { CloudApiSender, HttpPreferencesClient, LoggingSender, NotConnectedQa } from "./clients.ts";
import { detectIntent, detectLanguage, normaliseKeyword } from "./consent.ts";
import { REPLY_KEYS, reply } from "./replies.ts";
import { signBody, verifySignature } from "./signature.ts";
import { parseWebhook } from "./webhook.ts";

describe("signature", () => {
  it("verifies the header Meta sends and rejects everything else", () => {
    const sig = signBody('{"a":1}', "s");
    expect(sig.startsWith("sha256=")).toBe(true);
    expect(verifySignature('{"a":1}', sig, "s")).toBe(true);
    expect(verifySignature('{"a":2}', sig, "s")).toBe(false);
    expect(verifySignature('{"a":1}', sig, "other")).toBe(false);
    expect(verifySignature('{"a":1}', undefined, "s")).toBe(false);
    expect(verifySignature('{"a":1}', sig, "")).toBe(false);
    expect(verifySignature('{"a":1}', "sha256=short", "s")).toBe(false);
  });
});

describe("consent keywords", () => {
  it.each([
    ["STOP", "opt_out"],
    ["stop!", "opt_out"],
    ["Band karo", "opt_out"],
    ["बंद", "opt_out"],
    ["start", "opt_in"],
    ["हाँ", "opt_in"],
    ["help", "help"],
    ["मदद", "help"],
    ["please stop sending", "message"],
    [null, "message"],
  ])("%s -> %s", (text, intent) => {
    expect(detectIntent(text)).toBe(intent);
  });

  it("normalises and detects language", () => {
    expect(normaliseKeyword("  Stop.  ")).toBe("STOP");
    expect(detectLanguage("शुरू")).toBe("hi");
    expect(detectLanguage("start")).toBe("en");
    expect(detectLanguage(null)).toBe("en");
  });
});

describe("replies", () => {
  it("has english and hindi for every key", () => {
    for (const key of REPLY_KEYS) {
      expect(reply(key, "en")).not.toBe("");
      expect(reply(key, "hi")).not.toBe(reply(key, "en"));
    }
    expect(() => reply("nope", "en")).toThrow("unknown reply");
  });
});

describe("webhook parsing", () => {
  it("ignores shapes it does not know", () => {
    expect(parseWebhook(null)).toEqual({ messages: [], statuses: [] });
    expect(
      parseWebhook({
        object: "whatsapp_business_account",
        entry: [{ changes: [{ value: { messages: ["x"] } }, 3] }, "y"],
      }),
    ).toEqual({
      messages: [],
      statuses: [],
    });
  });

  it("maps a non-text message with a null text", () => {
    const parsed = parseWebhook({
      object: "whatsapp_business_account",
      entry: [
        {
          changes: [
            {
              value: {
                metadata: { phone_number_id: "42" },
                messages: [{ from: "1", id: "m", timestamp: "t", type: "image" }],
              },
            },
          ],
        },
      ],
    });
    expect(parsed.messages).toEqual([
      { id: "m", from: "1", timestamp: "t", text: null, type: "image", phoneNumberId: "42" },
    ]);
  });
});

describe("clients", () => {
  it("preferences client PUTs and GETs the notification service", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      if (init?.method === "PUT") return new Response("{}", { status: 200 });
      if (calls.length === 2) return new Response("", { status: 404 });
      return new Response(JSON.stringify({ opted_in: true }), { status: 200 });
    }) as unknown as typeof fetch;
    const client = new HttpPreferencesClient("http://n.test/", fetchImpl);
    await client.setOptIn("+91 9", true, "hi");
    expect(calls[0]?.url).toBe("http://n.test/v1/notification/preferences/whatsapp/%2B91%209");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      opted_in: true,
      source: "whatsapp_keyword",
      language: "hi",
    });
    expect(await client.isOptedIn("x")).toBe(false);
    expect(await client.isOptedIn("x")).toBe(true);
  });

  it("preferences client raises on server errors", async () => {
    const fetchImpl = vi.fn(
      async () => new Response("", { status: 500 }),
    ) as unknown as typeof fetch;
    const client = new HttpPreferencesClient("http://n.test", fetchImpl);
    await expect(client.setOptIn("1", true, "en")).rejects.toThrow("preferences: 500");
    await expect(client.isOptedIn("1")).rejects.toThrow("preferences: 500");
  });

  it("cloud api sender posts a text message with the bearer token", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toBe("https://graph.facebook.com/v21.0/42/messages");
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer tok");
      expect(JSON.parse(String(init?.body)).text.body).toBe("hi");
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;
    await new CloudApiSender("42", "tok", "v21.0", fetchImpl).sendText("9", "hi");
    const failing = vi.fn(
      async () => new Response("boom", { status: 400 }),
    ) as unknown as typeof fetch;
    await expect(
      new CloudApiSender("42", "tok", "v21.0", failing).sendText("9", "hi"),
    ).rejects.toThrow("cloud api: 400 boom");
  });

  it("logging sender keeps the reply in process and masks the number", async () => {
    const lines: string[] = [];
    const sender = new LoggingSender((line) => lines.push(line));
    await sender.sendText("919876543210", "hello");
    expect(sender.sent).toEqual([{ to: "919876543210", body: "hello" }]);
    expect(lines[0]).toContain("********3210");
    expect(await new NotConnectedQa().ask()).toBeNull();
  });
});

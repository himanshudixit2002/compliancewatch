import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_BOT_CLIENT_ID,
  IdentityTokenSource,
  SERVICE_TOKENS_PATH,
  authorizedFetch,
  identityTokenSource,
} from "./auth.ts";
import {
  CloudApiSender,
  DEFAULT_NOTICE_VERSION,
  HttpConsentLedger,
  HttpPreferencesClient,
  HttpReceiptsClient,
  LoggingSender,
  NoConsentLedger,
  NoReceiptsForwarding,
  NotConnectedQa,
  consentLedger,
  receiptsClient,
} from "./clients.ts";
import { detectIntent, detectLanguage, normaliseKeyword } from "./consent.ts";
import { handleInbound, maskNumber } from "./conversation.ts";
import { isEmpty, isoFromUnix, receiptsOf } from "./receipts.ts";
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

describe("status updates", () => {
  function statuses(...items: unknown[]) {
    return parseWebhook({
      object: "whatsapp_business_account",
      entry: [{ changes: [{ value: { statuses: items } }] }],
    }).statuses;
  }

  it("keep the code and title of a failure's first error", () => {
    const [failed, delivered, odd] = statuses(
      {
        id: "wamid.1",
        recipient_id: "919876543210",
        status: "failed",
        timestamp: "1790000000",
        errors: [
          { code: 131047, title: "Re-engagement message", message: "more than 24 hours" },
          { code: 1, title: "second" },
        ],
      },
      { id: "wamid.2", recipient_id: "9", status: "delivered", timestamp: "1790000001" },
      { id: "wamid.3", status: "failed", timestamp: "1", errors: [{ code: "131026" }, 3] },
    );
    expect(failed).toEqual({
      id: "wamid.1",
      recipient: "919876543210",
      status: "failed",
      timestamp: "1790000000",
      errorCode: 131047,
      errorTitle: "Re-engagement message",
    });
    expect([delivered?.errorCode, delivered?.errorTitle]).toEqual([null, ""]);
    expect([odd?.errorCode, odd?.errorTitle]).toEqual([null, ""]);
  });

  it("become the reports notification takes, dropping what it could not read", () => {
    const parsed = {
      statuses: statuses(
        { id: "wamid.1", status: "read", timestamp: "1790000000" },
        { id: "", status: "read", timestamp: "1790000000" },
        { id: "wamid.2", status: "", timestamp: "1790000000" },
        { id: "wamid.3", status: "sent", timestamp: "yesterday" },
      ),
      messages: [
        { id: "m1", from: "91", timestamp: "20", text: "a", type: "text", phoneNumberId: "4" },
        { id: "m2", from: "91", timestamp: "10", text: "b", type: "text", phoneNumberId: "4" },
        { id: "m3", from: "", timestamp: "30", text: "c", type: "text", phoneNumberId: "4" },
        { id: "m4", from: "92", timestamp: "", text: "d", type: "text", phoneNumberId: "4" },
      ],
    };
    const body = receiptsOf(parsed);
    expect(body).toEqual({
      statuses: [
        { provider_message_id: "wamid.1", status: "read", at: "2026-09-21T14:13:20.000Z" },
      ],
      inbound: [{ address: "91", at: "1970-01-01T00:00:20.000Z" }],
    });
    expect(isEmpty(body)).toBe(false);
    expect(isEmpty(receiptsOf({ statuses: [], messages: [] }))).toBe(true);
    expect(isoFromUnix("1.5")).toBeNull();
    expect(isoFromUnix("0")).toBe("1970-01-01T00:00:00.000Z");
  });
});

describe("clients", () => {
  it("receipts client posts to notification and raises when it refuses", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response("{}", { status: calls.length === 1 ? 200 : 401 });
    }) as unknown as typeof fetch;
    const client = new HttpReceiptsClient("http://n.test/", "bot", fetchImpl);
    const body = { statuses: [], inbound: [{ address: "91", at: "1970-01-01T00:00:00.000Z" }] };
    await client.forward(body);
    expect(calls[0]?.url).toBe("http://n.test/v1/notification/receipts/whatsapp");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual(body);
    await expect(client.forward(body)).rejects.toThrow("receipts: 401");
    await new NoReceiptsForwarding().forward();
  });

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

  it("consent ledger posts the keyword as a channel consent with the service token", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response("{}", { status: calls.length === 1 ? 201 : 200 });
    }) as unknown as typeof fetch;
    const at = new Date("2026-09-29T06:30:00Z");
    const ledger = new HttpConsentLedger("http://i.test/", "svc", "notice 1", fetchImpl, () => at);
    await ledger.record("919876543210", true, "START", "wamid.1", "en");
    await ledger.record("919876543210", false, "बंद", "wamid.2", "hi");
    expect(calls[0]?.url).toBe("http://i.test/v1/identity/channel-consents");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({
      "content-type": "application/json",
      "x-cw-service-token": "svc",
    });
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      channel: "whatsapp",
      subject: "919876543210",
      purpose: "whatsapp_reminders",
      granted: true,
      source: "whatsapp_keyword",
      notice_version: "notice 1",
      evidence:
        "keyword START in WhatsApp message wamid.1 at 2026-09-29T06:30:00.000Z, language en",
      message_id: "wamid.1",
    });
    expect(JSON.parse(String(calls[1]?.init?.body))).toMatchObject({
      granted: false,
      evidence: "keyword बंद in WhatsApp message wamid.2 at 2026-09-29T06:30:00.000Z, language hi",
    });
  });

  it("consent ledger raises when identity refuses", async () => {
    const fetchImpl = vi.fn(
      async () => new Response("", { status: 401 }),
    ) as unknown as typeof fetch;
    const ledger = new HttpConsentLedger("http://i.test", "wrong", undefined, fetchImpl);
    await expect(ledger.record("1", true, "START", "m", "en")).rejects.toThrow("consents: 401");
  });

  it("the environment picks the consent ledger", () => {
    const lines: string[] = [];
    const off = consentLedger({}, fetch, (line) => lines.push(line));
    expect(off).toBeInstanceOf(NoConsentLedger);
    expect(() => consentLedger({ WHATSAPP_CONSENT_RECORDING_ENABLED: "true" })).toThrow(
      "needs IDENTITY_SERVICE_TOKEN",
    );
    const on = consentLedger({
      WHATSAPP_CONSENT_RECORDING_ENABLED: "true",
      IDENTITY_SERVICE_TOKEN: "svc",
    });
    expect(on).toBeInstanceOf(HttpConsentLedger);
    expect(DEFAULT_NOTICE_VERSION).toBe("whatsapp-consent 0.1-draft");
  });

  it("the no-op ledger only logs, with the number masked", async () => {
    const lines: string[] = [];
    await new NoConsentLedger((line) => lines.push(line)).record(
      "919876543210",
      false,
      "STOP",
      "m",
    );
    expect(lines).toEqual([
      "whatsapp-bot: consent recording disabled; would record the opt-out of ********3210 (keyword STOP, message m)",
    ]);
    expect(maskNumber("12")).toBe("12");
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

describe("conversation", () => {
  it("logs a consent failure to stderr when no log is given", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const handled = await handleInbound(
        {
          id: "m",
          from: "919876543210",
          timestamp: "1",
          text: "START",
          type: "text",
          phoneNumberId: "42",
        },
        {
          preferences: {
            async setOptIn() {},
            async isOptedIn() {
              return false;
            },
          },
          consents: {
            async record() {
              throw new Error("down");
            },
          },
          sender: { async sendText() {} },
          qa: { ask: async () => null },
        },
      );
      expect(handled.replied).toBe(reply("try_again_later", "en"));
      expect(error).toHaveBeenCalledWith(expect.stringContaining("********3210"));
    } finally {
      error.mockRestore();
    }
  });
});

describe("service token", () => {
  const IDENTITY = "http://i.test";
  /** The dev client secret these tests exchange; the fake identity checks it. */
  const CLIENT_SECRET = "s".repeat(32);

  type Call = { url: string; init?: RequestInit };

  /** Identity's token route: numbers the tokens it issues, each valid for `expiresIn` seconds. */
  function identity(expiresIn: unknown = 600) {
    const calls: Call[] = [];
    let issued = 0;
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      issued += 1;
      return new Response(
        JSON.stringify({
          access_token: `bot-token-${issued}`,
          token_type: "Bearer",
          expires_in: expiresIn,
          scopes: ["notification:preferences"],
        }),
        { status: 200 },
      );
    }) as unknown as typeof fetch;
    return { calls, fetchImpl };
  }

  function clock(start = 1_000_000) {
    const time = { now: start };
    return { time, now: () => time.now };
  }

  it("exchanges the client credentials and keeps the token until a minute before it expires", async () => {
    const { calls, fetchImpl } = identity(600);
    const { time, now } = clock();
    const source = new IdentityTokenSource(
      `${IDENTITY}/`,
      "whatsapp-bot",
      CLIENT_SECRET,
      fetchImpl,
      now,
    );
    expect(await source.token()).toBe("bot-token-1");
    expect(calls[0]?.url).toBe(`${IDENTITY}${SERVICE_TOKENS_PATH}`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      client_id: "whatsapp-bot",
      client_secret: CLIENT_SECRET,
    });
    time.now += 539_000;
    expect(await source.token()).toBe("bot-token-1");
    time.now += 1_000;
    expect(await source.token()).toBe("bot-token-2");
    expect(calls).toHaveLength(2);
  });

  it("refreshes a short-lived token at half its lifetime", async () => {
    const { fetchImpl } = identity(60);
    const { time, now } = clock();
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, fetchImpl, now);
    expect(await source.token()).toBe("bot-token-1");
    time.now += 29_999;
    expect(await source.token()).toBe("bot-token-1");
    time.now += 1;
    expect(await source.token()).toBe("bot-token-2");
  });

  it("callers waiting on a fetch share it, and an invalidated token is fetched again", async () => {
    const { calls, fetchImpl } = identity();
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, fetchImpl);
    const tokens = await Promise.all([source.token(), source.token(), source.token()]);
    expect(tokens).toEqual(["bot-token-1", "bot-token-1", "bot-token-1"]);
    expect(calls).toHaveLength(1);
    source.invalidate("some-other-token");
    expect(await source.token()).toBe("bot-token-1");
    source.invalidate("bot-token-1");
    expect(await source.token()).toBe("bot-token-2");
  });

  it("a refusal, an outage or an answer without a token is an error, and nothing is cached", async () => {
    const refusing = vi.fn(
      async () => new Response(JSON.stringify({ type: "x" }), { status: 401 }),
    ) as unknown as typeof fetch;
    await expect(
      new IdentityTokenSource(IDENTITY, "whatsapp-bot", "wrong", refusing).token(),
    ).rejects.toThrow("identity token: 401 for client whatsapp-bot");
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    await expect(
      new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, down).token(),
    ).rejects.toThrow("identity unreachable for client whatsapp-bot");
    for (const body of ["not json", "[]", JSON.stringify({ access_token: "t", expires_in: 0 })]) {
      const odd = vi.fn(async () => new Response(body, { status: 200 })) as unknown as typeof fetch;
      await expect(
        new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, odd).token(),
      ).rejects.toThrow("lacks a bearer access_token and expires_in");
    }
    const mac = vi.fn(
      async () =>
        new Response(JSON.stringify({ access_token: "t", expires_in: 60, token_type: "mac" })),
    ) as unknown as typeof fetch;
    await expect(
      new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, mac).token(),
    ).rejects.toThrow("lacks a bearer");
    const { fetchImpl } = identity();
    let outage = true;
    const flaky = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (!outage) return fetchImpl(url, init);
      outage = false;
      return new Response("", { status: 503 });
    }) as unknown as typeof fetch;
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, flaky);
    await expect(source.token()).rejects.toThrow("identity token: 503");
    expect(await source.token()).toBe("bot-token-1");
  });

  it("needs a client id and a secret", () => {
    expect(() => new IdentityTokenSource(IDENTITY, " ", CLIENT_SECRET)).toThrow("client id");
    expect(() => new IdentityTokenSource(IDENTITY, "whatsapp-bot", "")).toThrow("client secret");
  });

  it("the environment configures a source only with a client secret", () => {
    expect(identityTokenSource({})).toBeNull();
    expect(identityTokenSource({ BOT_SERVICE_CLIENT_SECRET: "" })).toBeNull();
    const source = identityTokenSource({ BOT_SERVICE_CLIENT_SECRET: CLIENT_SECRET });
    expect(source?.clientId).toBe(DEFAULT_BOT_CLIENT_ID);
    const named = identityTokenSource({
      BOT_SERVICE_CLIENT_SECRET: CLIENT_SECRET,
      BOT_SERVICE_CLIENT_ID: "bot-staging",
    });
    expect(named?.clientId).toBe("bot-staging");
  });

  it("authorized fetch sends the bearer and retries once with a fresh token after a 401", async () => {
    const { fetchImpl: tokenFetch } = identity();
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, tokenFetch);
    const seen: string[] = [];
    const service = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const authorization = (init?.headers as Record<string, string>).authorization ?? "";
      seen.push(authorization);
      return authorization === "Bearer bot-token-1"
        ? new Response("{}", {
            status: 401,
            headers: { "www-authenticate": 'Bearer error="invalid_token"' },
          })
        : new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;
    const res = await authorizedFetch(service, source, "http://n.test/x", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).toBe(200);
    expect(seen).toEqual(["Bearer bot-token-1", "Bearer bot-token-2"]);
    const refusing = vi.fn(
      async () =>
        new Response(JSON.stringify({ type: "urn:compliancewatch:problem:auth-token-invalid" }), {
          status: 401,
        }),
    ) as unknown as typeof fetch;
    expect((await authorizedFetch(refusing, source, "http://n.test/x")).status).toBe(401);
    expect(refusing).toHaveBeenCalledTimes(2);
  });

  it("authorized fetch returns a 401 about something else without a new token", async () => {
    const { fetchImpl: tokenFetch, calls } = identity();
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, tokenFetch);
    const wrongSecret = JSON.stringify({
      type: "urn:compliancewatch:problem:receipt-token-invalid",
    });
    const service = vi.fn(
      async () => new Response(wrongSecret, { status: 401 }),
    ) as unknown as typeof fetch;
    const res = await authorizedFetch(service, source, "http://n.test/x");
    expect(res.status).toBe(401);
    expect(await res.text()).toBe(wrongSecret);
    expect(service).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    const bare = vi.fn(async () => new Response("", { status: 401 })) as unknown as typeof fetch;
    expect((await authorizedFetch(bare, source, "http://n.test/x")).status).toBe(401);
    expect(bare).toHaveBeenCalledTimes(1);
  });

  it("preferences, receipts and consents carry the bearer when a source is configured", async () => {
    const { fetchImpl: tokenFetch } = identity();
    const source = new IdentityTokenSource(IDENTITY, "whatsapp-bot", CLIENT_SECRET, tokenFetch);
    const calls: Call[] = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      if (init?.method === undefined) return new Response(JSON.stringify({ opted_in: true }));
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;
    const preferences = new HttpPreferencesClient("http://n.test", fetchImpl, source);
    await preferences.setOptIn("919876543210", true, "en");
    expect(await preferences.isOptedIn("919876543210")).toBe(true);
    await new HttpReceiptsClient("http://n.test", "", fetchImpl, source).forward({
      statuses: [],
      inbound: [],
    });
    await new HttpReceiptsClient("http://n.test", "bot", fetchImpl, source).forward({
      statuses: [],
      inbound: [],
    });
    const at = () => new Date("2026-09-29T06:30:00Z");
    await new HttpConsentLedger("http://i.test", "", undefined, fetchImpl, at, source).record(
      "919876543210",
      true,
      "START",
      "wamid.1",
      "en",
    );
    const headers = calls.map((call) => call.init?.headers);
    expect(headers).toEqual([
      { "content-type": "application/json", authorization: "Bearer bot-token-1" },
      { authorization: "Bearer bot-token-1" },
      { "content-type": "application/json", authorization: "Bearer bot-token-1" },
      {
        "content-type": "application/json",
        "x-cw-bot-token": "bot",
        authorization: "Bearer bot-token-1",
      },
      { "content-type": "application/json", authorization: "Bearer bot-token-1" },
    ]);
  });

  it("the environment's clients accept the service token in place of the shared tokens", () => {
    const source = identityTokenSource({ BOT_SERVICE_CLIENT_SECRET: CLIENT_SECRET });
    const warnings: string[] = [];
    expect(receiptsClient({}, fetch, (line) => warnings.push(line), source)).toBeInstanceOf(
      HttpReceiptsClient,
    );
    expect(warnings).toEqual([]);
    expect(
      consentLedger({ WHATSAPP_CONSENT_RECORDING_ENABLED: "true" }, fetch, console.log, source),
    ).toBeInstanceOf(HttpConsentLedger);
    expect(() => consentLedger({ WHATSAPP_CONSENT_RECORDING_ENABLED: "true" })).toThrow(
      "needs IDENTITY_SERVICE_TOKEN or BOT_SERVICE_CLIENT_SECRET",
    );
  });
});

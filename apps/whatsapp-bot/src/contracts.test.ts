/**
 * Consumer side of the bot's contracts with the services it calls
 * (packages/contracts/consumers/whatsapp-bot). Each client runs against a fetch that expects the
 * recorded requests in order, fails on any difference, and answers with the recorded response.
 * The provider side replays the same files against the real services
 * (services/<provider>/tests/contract/test_consumers.py), so a change on either side that breaks
 * the other fails a test.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { HttpConsentLedger, HttpPreferencesClient, HttpReceiptsClient } from "./clients.ts";

interface Interaction {
  readonly description: string;
  readonly request: {
    readonly method: string;
    readonly path: string;
    readonly headers?: Record<string, string>;
    readonly body?: unknown;
  };
  readonly response: { readonly status: number; readonly body?: unknown };
}

interface Contract {
  readonly consumer: string;
  readonly provider: string;
  readonly interactions: readonly Interaction[];
}

const BASE_URL = "http://provider.test";
const NUMBER = "919876543210";
const STRANGER = "919999999999";
const SERVICE_TOKEN = "test-channel-token";
const BOT_TOKEN = "bot-token-for-tests";
const AT = new Date("2026-09-29T06:30:00Z");

function load(provider: string): Contract {
  const file = new URL(
    `../../../packages/contracts/consumers/whatsapp-bot/${provider}.json`,
    import.meta.url,
  );
  const contract = JSON.parse(readFileSync(file, "utf8")) as Contract;
  expect([contract.consumer, contract.provider]).toEqual(["whatsapp-bot", provider]);
  return contract;
}

/** A fetch that plays the provider: the contract's interactions, in order, and nothing else. */
function replaying(contract: Contract) {
  const pending = [...contract.interactions];
  const fetchImpl = async (input: string | URL | Request, init?: RequestInit) => {
    const next = pending.shift();
    if (next === undefined) throw new Error(`request after the last interaction: ${String(input)}`);
    const url = new URL(String(input));
    expect(url.origin).toBe(BASE_URL);
    const sent = {
      method: init?.method ?? "GET",
      path: url.pathname + url.search,
      headers: init?.headers ?? {},
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    };
    expect(sent, next.description).toEqual({
      method: next.request.method,
      path: next.request.path,
      headers: next.request.headers ?? {},
      body: next.request.body,
    });
    return new Response(
      next.response.body === undefined ? null : JSON.stringify(next.response.body),
      { status: next.response.status, headers: { "content-type": "application/json" } },
    );
  };
  return { fetchImpl: fetchImpl as typeof fetch, pending };
}

describe("consumer contract with notification", () => {
  it("the preferences and receipts clients send the recorded requests", async () => {
    const { fetchImpl, pending } = replaying(load("notification"));
    const client = new HttpPreferencesClient(BASE_URL, fetchImpl);
    await client.setOptIn(NUMBER, true, "en");
    expect(await client.isOptedIn(NUMBER)).toBe(true);
    await client.setOptIn(NUMBER, false, "hi");
    expect(await client.isOptedIn(NUMBER)).toBe(false);
    expect(await client.isOptedIn(STRANGER)).toBe(false);
    const at = AT.toISOString();
    const inbound = [{ address: NUMBER, at }];
    await new HttpReceiptsClient(BASE_URL, BOT_TOKEN, fetchImpl).forward({
      statuses: [
        {
          provider_message_id: "wamid.contract.1",
          status: "failed",
          at,
          error_code: 131026,
          error_title: "Message undeliverable",
        },
      ],
      inbound,
    });
    await expect(
      new HttpReceiptsClient(BASE_URL, "not-the-bot-token", fetchImpl).forward({
        statuses: [],
        inbound,
      }),
    ).rejects.toThrow("receipts: 401");
    expect(pending).toEqual([]);
  });
});

describe("consumer contract with identity", () => {
  it("the consent ledger sends the recorded requests and reads the recorded answers", async () => {
    const { fetchImpl, pending } = replaying(load("identity"));
    const ledger = new HttpConsentLedger(BASE_URL, SERVICE_TOKEN, undefined, fetchImpl, () => AT);
    await ledger.record(NUMBER, true, "START", "wamid.contract.1", "en");
    await ledger.record(NUMBER, true, "START", "wamid.contract.1", "en");
    await ledger.record(NUMBER, false, "बंद", "wamid.contract.2", "hi");
    const wrongToken = new HttpConsentLedger(
      BASE_URL,
      "not-the-channel-token",
      undefined,
      fetchImpl,
      () => AT,
    );
    await expect(
      wrongToken.record(NUMBER, true, "START", "wamid.contract.3", "en"),
    ).rejects.toThrow("consents: 401");
    expect(pending).toEqual([]);
  });
});

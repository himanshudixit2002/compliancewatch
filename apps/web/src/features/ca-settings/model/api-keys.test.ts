import { describe, expect, it } from "vitest";
import { isMessageKey } from "@/shared/i18n";
import {
  API_KEY_STATUS_LABEL,
  API_KEY_STATUS_TONE,
  KEY_PREFIX_SHOWN,
  apiKeyCounts,
  apiKeyStatus,
  keyHint,
  sortApiKeys,
} from "./api-keys";
import type { ApiKey, ApiKeyStatus } from "./api-keys";

function apiKey(overrides: Partial<ApiKey>): ApiKey {
  return {
    id: "key_1",
    name: "Tally sync",
    prefix: "cw_live_",
    lastFour: "3f9a",
    createdAt: "2026-05-04T05:00:00Z",
    lastUsedAt: null,
    revokedAt: null,
    ...overrides,
  };
}

describe("apiKeyStatus", () => {
  it("is active until the key is revoked", () => {
    expect(apiKeyStatus(apiKey({}))).toBe("active");
    expect(apiKeyStatus(apiKey({ revokedAt: "2026-06-01T05:00:00Z" }))).toBe("revoked");
  });

  it("words and tones every status", () => {
    const statuses: ApiKeyStatus[] = ["active", "revoked"];
    for (const status of statuses) {
      expect(isMessageKey(API_KEY_STATUS_LABEL[status])).toBe(true);
    }
    expect(statuses.map((status) => API_KEY_STATUS_TONE[status])).toEqual(["success", "neutral"]);
  });
});

describe("keyHint", () => {
  it("shows the prefix and the last four characters around an ellipsis", () => {
    expect(keyHint(apiKey({}))).toBe("cw_live_…3f9a");
  });

  it("never shows more of a key than the hint allows, whatever the list carried", () => {
    const secret = "cw_live_9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e";
    const hint = keyHint({ prefix: secret, lastFour: secret });
    expect(hint).toBe(`${secret.slice(0, KEY_PREFIX_SHOWN)}…${secret.slice(-4)}`);
    expect(hint).not.toContain(secret);
  });
});

describe("sortApiKeys", () => {
  it("puts working keys first, newest first, without changing the input", () => {
    const input = [
      apiKey({ id: "old", createdAt: "2026-01-01T05:00:00Z" }),
      apiKey({
        id: "revoked",
        createdAt: "2026-09-01T05:00:00Z",
        revokedAt: "2026-09-02T05:00:00Z",
      }),
      apiKey({ id: "new", createdAt: "2026-08-01T05:00:00Z" }),
      apiKey({
        id: "revoked-old",
        createdAt: "2025-12-01T05:00:00Z",
        revokedAt: "2026-01-02T05:00:00Z",
      }),
    ];
    expect(sortApiKeys(input).map((key) => key.id)).toEqual([
      "new",
      "old",
      "revoked",
      "revoked-old",
    ]);
    expect(input[0]?.id).toBe("old");
  });
});

describe("apiKeyCounts", () => {
  it("counts the keys, the working ones and the revoked ones", () => {
    expect(
      apiKeyCounts([
        apiKey({ id: "a" }),
        apiKey({ id: "b", revokedAt: "2026-06-01T05:00:00Z" }),
        apiKey({ id: "c" }),
      ]),
    ).toEqual({ total: 3, active: 2, revoked: 1 });
    expect(apiKeyCounts([])).toEqual({ total: 0, active: 0, revoked: 0 });
  });
});

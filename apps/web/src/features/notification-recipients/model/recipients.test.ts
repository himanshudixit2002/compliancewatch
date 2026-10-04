import { describe, expect, it } from "vitest";
import type { Recipient } from "@/entities/notification/types";
import { isMessageKey } from "@/shared/i18n";
import {
  CHANNEL_LABEL,
  DIGEST_LABEL,
  ROLE_LABEL,
  recipientSummary,
  rolesFor,
  sortRecipients,
} from "./recipients";

function recipient(overrides: Partial<Recipient>): Recipient {
  return {
    id: "r",
    userId: null,
    role: "owner",
    language: "en",
    digestMode: "off",
    byDigest: false,
    orgLabel: "Org",
    addresses: [],
    businesses: [],
    createdAt: "2000-01-01T00:00:00Z",
    updatedAt: "2000-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("wording maps", () => {
  it("label every recipient role, channel and delivery", () => {
    for (const key of [
      ...Object.values(ROLE_LABEL),
      ...Object.values(CHANNEL_LABEL),
      ...Object.values(DIGEST_LABEL),
    ]) {
      expect(isMessageKey(key), key).toBe(true);
    }
  });
});

describe("rolesFor", () => {
  it("offers a business's own roles, a CA firm's, and none to the internal tenant", () => {
    expect(rolesFor("business")).toEqual(["owner", "staff"]);
    expect(rolesFor("ca_firm")).toEqual(["ca_admin", "ca_staff"]);
    expect(rolesFor("internal")).toEqual([]);
  });
});

describe("sortRecipients", () => {
  it("orders by organisation with unnamed recipients last, then by when they were added", () => {
    const sorted = sortRecipients([
      recipient({ id: "1", orgLabel: "", createdAt: "2000-01-02T00:00:00Z" }),
      recipient({ id: "2", orgLabel: "Zed" }),
      recipient({ id: "3", orgLabel: "Alpha" }),
      recipient({ id: "4", orgLabel: "", createdAt: "2000-01-01T00:00:00Z" }),
    ]);
    expect(sorted.map((r) => r.id)).toEqual(["3", "2", "4", "1"]);
  });
});

describe("recipientSummary", () => {
  it("counts recipients, those reachable on each channel and those on the digest", () => {
    expect(
      recipientSummary([
        recipient({
          addresses: [
            { channel: "whatsapp", address: "+910000000001" },
            { channel: "whatsapp", address: "+910000000002" },
          ],
          byDigest: true,
        }),
        recipient({
          addresses: [
            { channel: "email", address: "a@example.com" },
            { channel: "whatsapp", address: "+910000000003" },
          ],
        }),
        recipient({}),
      ]),
    ).toEqual({ total: 3, whatsapp: 2, email: 1, byDigest: 1 });
  });
});

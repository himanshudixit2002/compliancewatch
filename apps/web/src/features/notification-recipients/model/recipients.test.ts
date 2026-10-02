import { describe, expect, it } from "vitest";
import { isMessageKey } from "@/shared/i18n";
import {
  CHANNEL_LABEL,
  ROLE_LABEL,
  languageName,
  recipientFromDto,
  recipientSummary,
  sortRecipients,
} from "./recipients";
import type { Recipient, RecipientDto } from "./recipients";

const DTO: RecipientDto = {
  id: "r1",
  user_id: null,
  org_label: "Rao & Co",
  role: "ca_admin",
  language: "hi",
  digest_mode: "daily",
  by_digest: true,
  addresses: [
    { channel: "email", address: "desk@rao.example", position: 2 },
    { channel: "whatsapp", address: "+919800000001", position: 1 },
  ],
  businesses: [
    { business_id: "b1", label: "Asha Traders" },
    { business_id: "b2", label: "Kiran Foods" },
  ],
  created_at: "2026-01-01T05:00:00Z",
  updated_at: "2026-04-10T05:00:00Z",
};

function recipient(overrides: Partial<Recipient>): Recipient {
  return {
    id: "r",
    orgLabel: "Org",
    role: "owner",
    language: "en",
    addresses: [],
    businesses: [],
    byDigest: false,
    updatedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("recipientFromDto", () => {
  it("orders the addresses by position and keeps the business labels", () => {
    expect(recipientFromDto(DTO)).toEqual({
      id: "r1",
      orgLabel: "Rao & Co",
      role: "ca_admin",
      language: "hi",
      addresses: [
        { channel: "whatsapp", address: "+919800000001" },
        { channel: "email", address: "desk@rao.example" },
      ],
      businesses: ["Asha Traders", "Kiran Foods"],
      byDigest: true,
      updatedAt: "2026-04-10T05:00:00Z",
    });
    expect(DTO.addresses[0]?.position).toBe(2);
  });
});

describe("wording maps", () => {
  it("label every recipient role and channel", () => {
    for (const key of [...Object.values(ROLE_LABEL), ...Object.values(CHANNEL_LABEL)]) {
      expect(isMessageKey(key)).toBe(true);
    }
  });
});

describe("sortRecipients", () => {
  it("orders by organisation with unnamed recipients last", () => {
    const sorted = sortRecipients([
      recipient({ id: "1", orgLabel: "" }),
      recipient({ id: "2", orgLabel: "Zed" }),
      recipient({ id: "3", orgLabel: "Alpha" }),
      recipient({ id: "4", orgLabel: "" }),
    ]);
    expect(sorted.map((r) => r.id)).toEqual(["3", "2", "1", "4"]);
  });
});

describe("recipientSummary", () => {
  it("counts recipients, those reachable on each channel and those on the digest", () => {
    expect(
      recipientSummary([
        recipient({
          addresses: [
            { channel: "whatsapp", address: "+91" },
            { channel: "whatsapp", address: "+92" },
          ],
          byDigest: true,
        }),
        recipient({
          addresses: [
            { channel: "email", address: "a@example.com" },
            { channel: "whatsapp", address: "+93" },
          ],
        }),
        recipient({}),
      ]),
    ).toEqual({ total: 3, whatsapp: 2, email: 1, byDigest: 1 });
  });
});

describe("languageName", () => {
  it("names a language, and falls back to the code for an unknown or invalid one", () => {
    expect(languageName("hi")).toBe("Hindi");
    expect(languageName("zz")).toBe("zz");
    expect(languageName("not a code")).toBe("not a code");
  });
});

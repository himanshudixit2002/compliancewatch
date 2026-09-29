// @vitest-environment node
import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { rememberRecipient } from "@/server/remembered-recipients";
import { OWNER_ID, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { EMAIL_KEY, TEMPLATE_DTOS, WHATSAPP_KEY, preferenceDto } from "@/test/notification-fixture";
import { getNotificationSettings } from "./queries";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const owner: ClientPrincipal = {
  userId: OWNER_ID,
  tenantId: "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b",
  tenantKind: "business",
  roles: ["owner"],
};

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(randomBytes(32)).toString("base64"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getNotificationSettings", () => {
  it("reads the preference of each remembered recipient, the templates and the consents", async () => {
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    await rememberRecipient(OWNER_ID, "email", EMAIL_KEY);
    const fake = fakeFetch([
      { method: "GET", path: "/v1/notification/templates", body: TEMPLATE_DTOS },
      { method: "GET", path: "/v1/identity/consents", body: summaryDto() },
      {
        method: "GET",
        path: `/v1/notification/preferences/whatsapp/${WHATSAPP_KEY}`,
        body: preferenceDto(),
      },
      {
        method: "GET",
        path: "/v1/notification/preferences/email/owner%40example.com",
        status: 503,
        problem: { title: "Notification is unavailable" },
      },
    ]);
    const result = await getNotificationSettings(owner, { fetchImpl: fake.fetchImpl });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.channels.map((channel) => channel.state.kind)).toEqual([
      "recorded",
      "error",
    ]);
  });

  it("asks for recipients without reading any preference", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/notification/templates", body: TEMPLATE_DTOS },
      { method: "GET", path: "/v1/identity/consents", body: summaryDto() },
    ]);
    const result = await getNotificationSettings(owner, { fetchImpl: fake.fetchImpl });
    expect(result.ok && result.value.channels.map((channel) => channel.state.kind)).toEqual([
      "no_recipient",
      "no_recipient",
    ]);
    expect(fake.requests).toHaveLength(2);
  });

  it("fails the page when the templates or the consents cannot be read", async () => {
    const noTemplates = await getNotificationSettings(owner, {
      fetchImpl: fakeFetch([
        { path: "/v1/notification/templates", status: 503, problem: { title: "Down" } },
        { path: "/v1/identity/consents", body: summaryDto() },
      ]).fetchImpl,
    });
    expect(!noTemplates.ok && noTemplates.error.message).toBe("Down");
    const noConsents = await getNotificationSettings(owner, {
      fetchImpl: fakeFetch([
        { path: "/v1/notification/templates", body: TEMPLATE_DTOS },
        { path: "/v1/identity/consents", status: 401, problem: { title: "No tenant" } },
      ]).fetchImpl,
    });
    expect(!noConsents.ok && noConsents.error.message).toBe("No tenant");
  });
});

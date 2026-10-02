// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { REQUEST_ID_HEADER, TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { OWNER_ID, summaryDto } from "@/test/consent-fixture";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import { TEMPLATE_DTOS, WHATSAPP_KEY, preferenceDto } from "@/test/notification-fixture";
import { notificationPreferencesGateway } from "./gateway";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const owner: ClientPrincipal = {
  userId: OWNER_ID,
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const PREFERENCE_PATH = `/v1/notification/preferences/whatsapp/${WHATSAPP_KEY}`;

function gatewayWith(routes: readonly FakeRoute[]) {
  const fake = fakeFetch(routes);
  return {
    fake,
    gateway: notificationPreferencesGateway({ session: owner, fetchImpl: fake.fetchImpl }),
  };
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("NotificationPreferencesGateway", () => {
  it("reads a recipient's preference uncached, and none recorded as null", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: PREFERENCE_PATH, body: preferenceDto() },
      {
        method: "GET",
        path: "/v1/notification/preferences/email/owner%40example.com",
        status: 404,
        problem: { type: "about:blank", title: "Not Found" },
      },
    ]);
    const found = await gateway.preference("whatsapp", WHATSAPP_KEY);
    expect(found.ok && found.value?.optedIn).toBe(true);
    expect(fake.requests[0]?.url).toBe(`http://localhost:8006${PREFERENCE_PATH}`);
    expect(fake.requests[0]?.cache).toBe("no-store");
    expect(fake.requests[0]?.headers[REQUEST_ID_HEADER]).toBeDefined();
    const none = await gateway.preference("email", "owner@example.com");
    expect(none).toMatchObject({ ok: true, value: null });
  });

  it("passes any other failure on", async () => {
    const { gateway } = gatewayWith([
      { method: "GET", path: PREFERENCE_PATH, status: 422, problem: { title: "Invalid" } },
    ]);
    const result = await gateway.preference("whatsapp", WHATSAPP_KEY);
    expect(!result.ok && result.error.kind).toBe("validation");
  });

  it("replaces a preference with the choice, the language and the quiet hours", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "PUT",
        path: PREFERENCE_PATH,
        body: preferenceDto({ opted_in: false, quiet_hours_start: "22:00" }),
      },
    ]);
    const saved = await gateway.save("whatsapp", WHATSAPP_KEY, {
      optedIn: false,
      source: "web_onboarding",
      language: "hi",
      quietHoursStart: "22:00",
      quietHoursEnd: "07:00",
    });
    expect(saved.ok && saved.value.quietHoursStart).toBe("22:00");
    expect(fake.requests[0]?.body).toEqual({
      opted_in: false,
      source: "web_onboarding",
      language: "hi",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
    });
  });

  it("keeps the templates under their tag for five minutes", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: "/v1/notification/templates", body: TEMPLATE_DTOS },
    ]);
    const templates = await gateway.templates();
    expect(templates.ok && templates.value.map((template) => template.language)).toEqual([
      "en",
      "hi",
      "en",
    ]);
    expect(fake.requests[0]?.next).toEqual({ revalidate: 300, tags: ["notification:templates"] });
  });

  it("reads the user's consents from identity with the tenant header", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: "/v1/identity/consents", body: summaryDto() },
    ]);
    const consents = await gateway.consents(OWNER_ID);
    expect(consents.ok && consents.value.subject).toBe(OWNER_ID);
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8001/v1/identity/consents?subject=${OWNER_ID}`,
    );
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT);
  });
});

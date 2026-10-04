// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import {
  BUSINESS_ID,
  RECIPIENT_ID,
  TEMPLATE_DTOS,
  recipientDto,
} from "@/test/notification-fixture";
import { recipientsGateway } from "./gateway";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const owner: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-0000000000a2",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const RECIPIENT_PATH = `/v1/notification/recipients/${RECIPIENT_ID}`;

function gatewayWith(routes: readonly FakeRoute[]) {
  const fake = fakeFetch(routes);
  return { fake, gateway: recipientsGateway({ session: owner, fetchImpl: fake.fetchImpl }) };
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("RecipientsGateway", () => {
  it("lists a business's recipients for the session's tenant, uncached", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: "/v1/notification/recipients",
        body: { items: [recipientDto()], next_cursor: "next" },
      },
    ]);
    const page = await gateway.list(BUSINESS_ID, 200);
    expect(page.ok && page.value.items[0]?.id).toBe(RECIPIENT_ID);
    expect(page.ok && page.value.nextCursor).toBe("next");
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8006/v1/notification/recipients?business_id=${BUSINESS_ID}&limit=200`,
    );
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(fake.requests[0]?.cache).toBe("no-store");
  });

  it("reads, replaces and removes one recipient", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: RECIPIENT_PATH, body: recipientDto() },
      { method: "PUT", path: RECIPIENT_PATH, body: recipientDto({ language: "hi" }) },
      { method: "DELETE", path: RECIPIENT_PATH, status: 204 },
    ]);
    expect((await gateway.get(RECIPIENT_ID)).ok).toBe(true);
    const saved = await gateway.put(RECIPIENT_ID, {
      role: "staff",
      userId: null,
      language: "hi",
      digestMode: "off",
      orgLabel: "",
      addresses: [{ channel: "whatsapp", address: "+910000000000" }],
      businesses: [{ businessId: BUSINESS_ID, label: "Example business" }],
    });
    expect(saved.ok && saved.value.language).toBe("hi");
    expect(fake.requests[1]?.body).toEqual({
      role: "staff",
      user_id: null,
      language: "hi",
      digest_mode: "off",
      org_label: "",
      addresses: [{ channel: "whatsapp", address: "+910000000000" }],
      businesses: [{ business_id: BUSINESS_ID, label: "Example business" }],
    });
    const removed = await gateway.remove(RECIPIENT_ID);
    expect(removed).toMatchObject({ ok: true, value: undefined });
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      `GET ${RECIPIENT_PATH}`,
      `PUT ${RECIPIENT_PATH}`,
      `DELETE ${RECIPIENT_PATH}`,
    ]);
  });

  it("passes a missing recipient on as not found", async () => {
    const { gateway } = gatewayWith([
      { method: "GET", path: RECIPIENT_PATH, status: 404, problem: { title: "Not found" } },
    ]);
    const missing = await gateway.get(RECIPIENT_ID);
    expect(!missing.ok && missing.error.kind).toBe("not_found");
  });

  it("keeps the templates under their tag and reads the tenant's businesses by name", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: "/v1/notification/templates", body: TEMPLATE_DTOS },
      {
        method: "GET",
        path: "/v1/businesses",
        body: {
          items: [
            {
              id: BUSINESS_ID,
              name: "Example business",
              pan: "AAAPE0001Z",
              gstins: [],
              updated_at: "2000-01-01T00:00:00Z",
            },
          ],
          next_cursor: null,
        },
      },
    ]);
    const templates = await gateway.templates();
    expect(templates.ok && templates.value).toHaveLength(TEMPLATE_DTOS.length);
    expect(fake.requests[0]?.next).toEqual({ revalidate: 300, tags: ["notification:templates"] });
    const businesses = await gateway.businesses(200);
    expect(businesses.ok && businesses.value.items[0]?.name).toBe("Example business");
    expect(fake.requests[1]?.url).toBe("http://localhost:8002/v1/businesses?limit=200");
    expect(fake.requests[1]?.headers[TENANT_HEADER]).toBe(TENANT);
  });
});

// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import { BUSINESS_ID, NOTIFICATION_ID, notificationDto } from "@/test/notification-fixture";
import { notificationsGateway } from "./gateway";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const OTHER_TENANT = "00000000-0000-4000-8000-0000000000a9";
const owner: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-0000000000a2",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

function gatewayWith(routes: readonly FakeRoute[], tenantId?: string) {
  const fake = fakeFetch(routes);
  return {
    fake,
    gateway: notificationsGateway({
      session: owner,
      fetchImpl: fake.fetchImpl,
      ...(tenantId === undefined ? {} : { tenantId }),
    }),
  };
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("NotificationsGateway", () => {
  it("reads a business's history with its filter and cursor, uncached, for the tenant", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: "/v1/notification/notifications",
        body: { items: [notificationDto()], next_cursor: "next" },
      },
    ]);
    const page = await gateway.page(BUSINESS_ID, { state: "failed", cursor: "now", limit: 25 });
    expect(page.ok && page.value.items[0]?.id).toBe(NOTIFICATION_ID);
    expect(page.ok && page.value.nextCursor).toBe("next");
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8006/v1/notification/notifications?business_id=${BUSINESS_ID}&limit=25&state=failed&cursor=now`,
    );
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(fake.requests[0]?.cache).toBe("no-store");
    await gateway.page(BUSINESS_ID, { limit: 25 });
    expect(fake.requests[1]?.url).toBe(
      `http://localhost:8006/v1/notification/notifications?business_id=${BUSINESS_ID}&limit=25`,
    );
  });

  it("reads one notification, and an admin lookup acts for the tenant it names", async () => {
    const { fake, gateway } = gatewayWith(
      [
        {
          method: "GET",
          path: `/v1/notification/notifications/${NOTIFICATION_ID}`,
          body: notificationDto(),
        },
      ],
      OTHER_TENANT,
    );
    const record = await gateway.get(NOTIFICATION_ID);
    expect(record.ok && record.value.state).toBe("failed");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(OTHER_TENANT);
  });

  it("names the business from the profile service and passes a missing one on", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: `/v1/businesses/${BUSINESS_ID}`,
        body: {
          id: BUSINESS_ID,
          name: "Example business",
          pan: "AAAPE0001Z",
          version: 1,
          created_at: "2000-01-01T00:00:00Z",
          updated_at: "2000-01-01T00:00:00Z",
          attributes: [],
          registrations: [],
        },
      },
    ]);
    expect(await gateway.business(BUSINESS_ID)).toMatchObject({
      ok: true,
      value: { id: BUSINESS_ID, name: "Example business", pan: "AAAPE0001Z" },
    });
    expect(fake.requests[0]?.url).toBe(`http://localhost:8002/v1/businesses/${BUSINESS_ID}`);
    const missing = await gateway.business("00000000-0000-4000-8000-0000000000ff");
    expect(!missing.ok && missing.error.kind).toBe("not_found");
  });
});

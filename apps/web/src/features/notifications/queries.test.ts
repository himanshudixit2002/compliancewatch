// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { TENANT_HEADER } from "@/server/api/client";
import {
  BUSINESS_ID,
  NOTIFICATION_ID,
  TEMPLATE_DTOS,
  notificationDto,
} from "@/test/notification-fixture";
import {
  getAdminNotification,
  getAdminNotifications,
  getReminder,
  getReminders,
  getTemplates,
} from "./queries";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const owner: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-0000000000a2",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const LIST = `/b/${BUSINESS_ID}/reminders`;
const FALLBACK = "00000000-0000-4000-8000-0000000000f0";

const BUSINESS = {
  id: BUSINESS_ID,
  name: "Example business",
  pan: "AAAPE0001Z",
  version: 1,
  created_at: "2000-01-01T00:00:00Z",
  updated_at: "2000-01-01T00:00:00Z",
  attributes: [],
  registrations: [],
};

function services(options: { business?: Response; list?: Response; one?: Response } = {}) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.pathname === `/v1/businesses/${BUSINESS_ID}`) {
      return options.business ?? jsonResponse(200, BUSINESS);
    }
    if (request.pathname === "/v1/notification/notifications") {
      return options.list ?? jsonResponse(200, { items: [notificationDto()], next_cursor: "next" });
    }
    if (request.pathname === `/v1/notification/notifications/${NOTIFICATION_ID}`) {
      return options.one ?? jsonResponse(200, notificationDto({ fallback_of: FALLBACK }));
    }
    return problemResponse(404);
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getReminders", () => {
  it("reads the business and a page of its history with the way on", async () => {
    const fake = services();
    const view = await getReminders(
      owner,
      BUSINESS_ID,
      { state: "failed" },
      {
        fetchImpl: fake.fetchImpl,
      },
    );
    expect(view.ok).toBe(true);
    if (!view.ok) return;
    expect(view.value.business).toEqual({
      id: BUSINESS_ID,
      name: "Example business",
      pan: "AAAPE0001Z",
    });
    expect(view.value.rows[0]?.href).toBe(`${LIST}/${NOTIFICATION_ID}`);
    expect(view.value.nextHref).toBe(`${LIST}?state=failed&cursor=next`);
    expect(view.value.firstHref).toBeNull();
    const list = fake.requests.find(
      (request) => request.pathname === "/v1/notification/notifications",
    );
    expect(list?.url).toContain("state=failed");
    expect(list?.url).toContain("limit=25");
  });

  it("is not found for a business the tenant does not hold, and passes a failed read on", async () => {
    const missing = await getReminders(
      owner,
      BUSINESS_ID,
      {},
      {
        fetchImpl: services({ business: problemResponse(404) }).fetchImpl,
      },
    );
    expect(!missing.ok && missing.error.kind).toBe("not_found");
    const failed = await getReminders(
      owner,
      BUSINESS_ID,
      {},
      {
        fetchImpl: services({ list: problemResponse(503) }).fetchImpl,
      },
    );
    expect(!failed.ok && failed.error.kind).toBe("unavailable");
  });
});

describe("getReminder", () => {
  it("reads one notification of the business with the way back and to the one it falls back from", async () => {
    const view = await getReminder(owner, BUSINESS_ID, NOTIFICATION_ID, {
      fetchImpl: services().fetchImpl,
    });
    expect(view.ok).toBe(true);
    if (!view.ok) return;
    expect(view.value.listHref).toBe(LIST);
    expect(view.value.fallbackHref).toBe(`${LIST}/${FALLBACK}`);
    expect(view.value.detail.id).toBe(NOTIFICATION_ID);
  });

  it("is not found for a notification of another business, or a missing one", async () => {
    const other = await getReminder(owner, BUSINESS_ID, NOTIFICATION_ID, {
      fetchImpl: services({
        one: jsonResponse(
          200,
          notificationDto({ business_id: "00000000-0000-4000-8000-0000000000b9" }),
        ),
      }).fetchImpl,
    });
    expect(!other.ok && other.error.kind).toBe("not_found");
    const gone = await getReminder(owner, BUSINESS_ID, NOTIFICATION_ID, {
      fetchImpl: services({ one: problemResponse(404) }).fetchImpl,
    });
    expect(!gone.ok && gone.error.kind).toBe("not_found");
    const missing = await getReminder(owner, BUSINESS_ID, NOTIFICATION_ID, {
      fetchImpl: services({ business: problemResponse(404) }).fetchImpl,
    });
    expect(!missing.ok && missing.error.kind).toBe("not_found");
    const plain = await getReminder(owner, BUSINESS_ID, NOTIFICATION_ID, {
      fetchImpl: services({ one: jsonResponse(200, notificationDto()) }).fetchImpl,
    });
    expect(plain.ok && plain.value.fallbackHref).toBeNull();
  });
});

const LOOKED_UP = "00000000-0000-4000-8000-0000000000a9";
const analyst: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-0000000000a3",
  tenantId: "00000000-0000-4000-8000-0000000000a0",
  tenantKind: "internal",
  roles: ["analyst"],
};

describe("getAdminNotifications", () => {
  it("reads the business's history for the tenant the lookup names, linking each with it", async () => {
    const fake = services();
    const view = await getAdminNotifications(
      analyst,
      { tenantId: LOOKED_UP, businessId: BUSINESS_ID },
      { state: "failed" },
      { fetchImpl: fake.fetchImpl },
    );
    expect(view.ok).toBe(true);
    if (!view.ok) return;
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(LOOKED_UP);
    expect(fake.requests.some((request) => request.pathname.startsWith("/v1/businesses"))).toBe(
      false,
    );
    expect(view.value.rows[0]?.href).toBe(
      `/admin/notifications/${NOTIFICATION_ID}?tenant=${LOOKED_UP}&business=${BUSINESS_ID}`,
    );
    expect(view.value.nextHref).toBe(
      `/admin/notifications?tenant=${LOOKED_UP}&business=${BUSINESS_ID}&state=failed&cursor=next`,
    );
  });

  it("passes a failed read on", async () => {
    const view = await getAdminNotifications(
      analyst,
      { tenantId: LOOKED_UP, businessId: BUSINESS_ID },
      {},
      { fetchImpl: services({ list: problemResponse(500) }).fetchImpl },
    );
    expect(!view.ok && view.error.kind).toBe("server");
  });
});

describe("getAdminNotification", () => {
  it("reads one notification for the tenant named, with the way back to its business", async () => {
    const fake = services();
    const view = await getAdminNotification(analyst, LOOKED_UP, NOTIFICATION_ID, {
      fetchImpl: fake.fetchImpl,
    });
    expect(view.ok).toBe(true);
    if (!view.ok) return;
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(LOOKED_UP);
    expect(view.value.tenantId).toBe(LOOKED_UP);
    expect(view.value.listHref).toBe(
      `/admin/notifications?tenant=${LOOKED_UP}&business=${BUSINESS_ID}`,
    );
    expect(view.value.fallbackHref).toBe(
      `/admin/notifications/${FALLBACK}?tenant=${LOOKED_UP}&business=${BUSINESS_ID}`,
    );
    const plain = await getAdminNotification(analyst, LOOKED_UP, NOTIFICATION_ID, {
      fetchImpl: services({ one: jsonResponse(200, notificationDto()) }).fetchImpl,
    });
    expect(plain.ok && plain.value.fallbackHref).toBeNull();
    const gone = await getAdminNotification(analyst, LOOKED_UP, NOTIFICATION_ID, {
      fetchImpl: services({ one: problemResponse(404) }).fetchImpl,
    });
    expect(!gone.ok && gone.error.kind).toBe("not_found");
  });
});

describe("getTemplates", () => {
  it("reads the templates without a tenant, cached under their tag", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/notification/templates", body: TEMPLATE_DTOS },
    ]);
    const rows = await getTemplates({ fetchImpl: fake.fetchImpl });
    expect(rows.ok && rows.value).toHaveLength(TEMPLATE_DTOS.length);
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    expect(fake.requests[0]?.next).toEqual({ revalidate: 300, tags: ["notification:templates"] });
  });
});

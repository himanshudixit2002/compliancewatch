// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import type { TenantKind } from "@/shared/config/roles";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import {
  BUSINESS_ID,
  RECIPIENT_ID,
  TEMPLATE_DTOS,
  recipientDto,
} from "@/test/notification-fixture";
import { getRecipientsPage } from "./queries";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const OTHER_ID = "00000000-0000-4000-8000-0000000000b2";
const NEW_ID = "00000000-0000-4000-8000-0000000000e9";
const PAGE = "/settings/notifications/recipients";
const owner: ClientPrincipal & { tenantKind: TenantKind } = {
  userId: "00000000-0000-4000-8000-0000000000a2",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

function summary(id: string, name: string) {
  return { id, name, pan: "AAAPE0001Z", gstins: [], updated_at: "2000-01-01T00:00:00Z" };
}

function services(
  options: {
    businesses?: unknown[];
    recipient?: Response;
    templates?: Response;
    list?: Response;
  } = {},
) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.pathname === "/v1/businesses") {
      return jsonResponse(200, {
        items: options.businesses ?? [
          summary(BUSINESS_ID, "Example business"),
          summary(OTHER_ID, "Example second business"),
        ],
        next_cursor: null,
      });
    }
    if (request.pathname === "/v1/notification/templates") {
      return options.templates ?? jsonResponse(200, TEMPLATE_DTOS);
    }
    if (request.pathname === "/v1/notification/recipients") {
      return options.list ?? jsonResponse(200, { items: [recipientDto()], next_cursor: null });
    }
    if (request.pathname === `/v1/notification/recipients/${RECIPIENT_ID}`) {
      return options.recipient ?? jsonResponse(200, recipientDto());
    }
    return problemResponse(404);
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getRecipientsPage", () => {
  it("shows the first business by name with its recipients and a fresh form", async () => {
    const fake = services();
    const page = await getRecipientsPage(owner, {}, PAGE, {
      fetchImpl: fake.fetchImpl,
      newRecipientId: () => NEW_ID,
    });
    expect(page.ok).toBe(true);
    if (!page.ok) return;
    expect(page.value.selected).toEqual({ id: BUSINESS_ID, name: "Example business" });
    expect(page.value.rows.map((row) => row.id)).toEqual([RECIPIENT_ID]);
    expect(page.value.form?.recipientId).toBe(NEW_ID);
    const list = fake.requests.find(
      (request) => request.pathname === "/v1/notification/recipients",
    );
    expect(list?.url).toContain(`business_id=${BUSINESS_ID}`);
  });

  it("shows the business asked for and the recipient to change", async () => {
    const fake = services();
    const page = await getRecipientsPage(
      owner,
      { businessId: OTHER_ID, editId: RECIPIENT_ID },
      PAGE,
      { fetchImpl: fake.fetchImpl },
    );
    expect(page.ok && page.value.selected?.id).toBe(OTHER_ID);
    expect(page.ok && page.value.form?.mode).toBe("change");
    expect(page.ok && page.value.form?.recipientId).toBe(RECIPIENT_ID);
  });

  it("answers not found for a business the tenant does not have", async () => {
    const page = await getRecipientsPage(
      owner,
      { businessId: "00000000-0000-4000-8000-0000000000ff" },
      PAGE,
      { fetchImpl: services().fetchImpl },
    );
    expect(!page.ok && page.error.kind).toBe("not_found");
  });

  it("offers the add form when the recipient to change is gone", async () => {
    const page = await getRecipientsPage(owner, { editId: RECIPIENT_ID }, PAGE, {
      fetchImpl: services({ recipient: problemResponse(404) }).fetchImpl,
    });
    expect(page.ok && page.value.editMissing).toBe(true);
    expect(page.ok && page.value.form?.mode).toBe("add");
  });

  it("asks for nothing more when the tenant has no business", async () => {
    const fake = services({ businesses: [] });
    const page = await getRecipientsPage(owner, {}, PAGE, { fetchImpl: fake.fetchImpl });
    expect(page.ok && page.value.selected).toBeNull();
    expect(
      fake.requests.some((request) => request.pathname === "/v1/notification/recipients"),
    ).toBe(false);
  });

  it("passes on the first failed read", async () => {
    const templates = await getRecipientsPage(owner, {}, PAGE, {
      fetchImpl: services({ templates: problemResponse(503, { title: "Templates down" }) })
        .fetchImpl,
    });
    expect(!templates.ok && templates.error.message).toBe("Templates down");
    const list = await getRecipientsPage(owner, {}, PAGE, {
      fetchImpl: services({ list: problemResponse(500) }).fetchImpl,
    });
    expect(!list.ok && list.error.kind).toBe("server");
    const edit = await getRecipientsPage(owner, { editId: RECIPIENT_ID }, PAGE, {
      fetchImpl: services({ recipient: problemResponse(500) }).fetchImpl,
    });
    expect(!edit.ok && edit.error.kind).toBe("server");
    const businesses = await getRecipientsPage(owner, {}, PAGE, {
      fetchImpl: fakeFetch([{ path: "/v1/businesses", status: 503, problem: {} }]).fetchImpl,
    });
    expect(!businesses.ok && businesses.error.kind).toBe("unavailable");
  });
});

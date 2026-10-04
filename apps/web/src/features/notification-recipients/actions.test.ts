// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import {
  BUSINESS_ID,
  RECIPIENT_ID,
  TEMPLATE_DTOS,
  recipientDto,
} from "@/test/notification-fixture";
import { removeRecipient, saveRecipient } from "./actions";
import { RECIPIENT_FIELDS, addressField, channelField } from "./model/recipient-form";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const TENANT = "00000000-0000-4000-8000-0000000000a1";
const OTHER_ID = "00000000-0000-4000-8000-0000000000b2";
const NEW_ID = "00000000-0000-4000-8000-0000000000e9";
const PAGE = "/settings/notifications/recipients";
const IDLE = { status: "idle" } as const;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: "00000000-0000-4000-8000-0000000000a2",
    tenantId: TENANT,
    tenantKind: "business",
    roles: ["owner"],
    displayName: "Example owner",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [key, value] of entries) data.append(key, value);
  return data;
}

function saveForm(recipientId: string): FormData {
  return form([
    [RECIPIENT_FIELDS.recipientId, recipientId],
    [RECIPIENT_FIELDS.returnBusiness, BUSINESS_ID],
    [RECIPIENT_FIELDS.role, "staff"],
    [RECIPIENT_FIELDS.language, "hi"],
    [RECIPIENT_FIELDS.digestMode, "daily"],
    [RECIPIENT_FIELDS.orgLabel, ""],
    [channelField(0), "whatsapp"],
    [addressField(0), "+91 00000 00007"],
    [RECIPIENT_FIELDS.businesses, BUSINESS_ID],
    [RECIPIENT_FIELDS.businesses, OTHER_ID],
  ]);
}

function summary(id: string, name: string) {
  return { id, name, pan: "AAAPE0001Z", gstins: [], updated_at: "2000-01-01T00:00:00Z" };
}

/** The businesses, the templates and the recipient routes as the services answer them. */
function services(options: { existing?: Response; put?: Response; remove?: Response } = {}) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.pathname === "/v1/businesses") {
      return jsonResponse(200, {
        items: [summary(BUSINESS_ID, "Example business"), summary(OTHER_ID, "Example other")],
        next_cursor: null,
      });
    }
    if (request.pathname === "/v1/notification/templates") return jsonResponse(200, TEMPLATE_DTOS);
    if (request.pathname.startsWith("/v1/notification/recipients/")) {
      const id = request.pathname.split("/").at(-1) as string;
      if (request.method === "GET") return options.existing ?? problemResponse(404);
      if (request.method === "PUT") {
        return options.put ?? jsonResponse(200, recipientDto({ ...(request.body as object), id }));
      }
      if (request.method === "DELETE") return options.remove ?? jsonResponse(204, undefined);
    }
    return problemResponse(404);
  });
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.clearAllMocks();
});

describe("saveRecipient", () => {
  it("registers a new recipient, its links named after the businesses, and returns to the page", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(saveRecipient(IDLE, saveForm(NEW_ID))).rejects.toThrow(
      `redirect ${PAGE}?business=${BUSINESS_ID}&saved=${NEW_ID}`,
    );
    const put = fake.requests.find((request) => request.method === "PUT");
    expect(put?.pathname).toBe(`/v1/notification/recipients/${NEW_ID}`);
    expect(put?.headers["x-tenant-id"]).toBe(TENANT);
    expect(put?.body).toEqual({
      role: "staff",
      user_id: null,
      language: "hi",
      digest_mode: "daily",
      org_label: "",
      addresses: [{ channel: "whatsapp", address: "+910000000007" }],
      businesses: [
        { business_id: BUSINESS_ID, label: "Example business" },
        { business_id: OTHER_ID, label: "Example other" },
      ],
    });
    expect(revalidatePath).toHaveBeenCalledWith(PAGE);
  });

  it("keeps what the form does not show when it replaces a recipient", async () => {
    await signedInAs();
    const existing = recipientDto({
      user_id: "00000000-0000-4000-8000-0000000000a9",
      language: "ta",
      businesses: [
        { business_id: BUSINESS_ID, label: "Example own label" },
        { business_id: "00000000-0000-4000-8000-0000000000b9", label: "Example far" },
      ],
    });
    const fake = services({ existing: jsonResponse(200, existing) });
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(
      saveRecipient(
        IDLE,
        form([
          [RECIPIENT_FIELDS.recipientId, RECIPIENT_ID],
          [RECIPIENT_FIELDS.role, "owner"],
          [RECIPIENT_FIELDS.language, "ta"],
          [RECIPIENT_FIELDS.digestMode, "off"],
          [channelField(0), "email"],
          [addressField(0), "owner@example.com"],
          [RECIPIENT_FIELDS.businesses, BUSINESS_ID],
          [RECIPIENT_FIELDS.businesses, "00000000-0000-4000-8000-0000000000b9"],
        ]),
      ),
    ).rejects.toThrow(`redirect ${PAGE}?business=${BUSINESS_ID}&saved=${RECIPIENT_ID}`);
    const put = fake.requests.find((request) => request.method === "PUT");
    expect(put?.body).toMatchObject({
      user_id: "00000000-0000-4000-8000-0000000000a9",
      language: "ta",
      businesses: [
        { business_id: BUSINESS_ID, label: "Example own label" },
        { business_id: "00000000-0000-4000-8000-0000000000b9", label: "Example far" },
      ],
    });
  });

  it("refuses a malformed form before writing anything", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveRecipient(
      IDLE,
      form([
        [RECIPIENT_FIELDS.recipientId, NEW_ID],
        [RECIPIENT_FIELDS.role, "admin"],
        [RECIPIENT_FIELDS.language, "en"],
        [RECIPIENT_FIELDS.digestMode, "off"],
      ]),
    );
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(Object.keys(state.fieldErrors ?? {}).sort()).toEqual(
      [RECIPIENT_FIELDS.businesses, RECIPIENT_FIELDS.role, addressField(0)].sort(),
    );
    expect(fake.requests.some((request) => request.method === "PUT")).toBe(false);
  });

  it("refuses a form without its recipient id, without calling a service", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveRecipient(IDLE, saveForm("not an id"));
    expect(state).toEqual({
      status: "error",
      formErrors: ["This form is out of date. Reload the page and try again."],
    });
    expect(fake.requests).toEqual([]);
  });

  it("returns the service's problem, field errors included", async () => {
    await signedInAs();
    const fake = services({
      put: problemResponse(422, {
        title: "Notification address invalid",
        errors: [
          {
            loc: ["body", "addresses", 0, "address"],
            msg: "Example message.",
            type: "value_error",
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveRecipient(IDLE, saveForm(NEW_ID));
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(state.problem?.title).toBe("Notification address invalid");
    expect(state.fieldErrors?.[addressField(0)]).toEqual(["Example message."]);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("passes on a failed read of the recipient", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ existing: problemResponse(503) }).fetchImpl);
    const state = await saveRecipient(IDLE, saveForm(NEW_ID));
    expect(state.status === "error" && state.problem?.title).toBe("Test problem 503");
  });

  it("sends a role the page does not admit to the forbidden page", async () => {
    await signedInAs({ roles: ["staff"] });
    vi.stubGlobal("fetch", services().fetchImpl);
    await expect(saveRecipient(IDLE, saveForm(NEW_ID))).rejects.toThrow("redirect /forbidden");
  });
});

describe("removeRecipient", () => {
  it("removes the recipient and returns to the business the page showed", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(
      removeRecipient(
        IDLE,
        form([
          [RECIPIENT_FIELDS.recipientId, RECIPIENT_ID],
          [RECIPIENT_FIELDS.returnBusiness, BUSINESS_ID],
        ]),
      ),
    ).rejects.toThrow(`redirect ${PAGE}?business=${BUSINESS_ID}&removed=1`);
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      `DELETE /v1/notification/recipients/${RECIPIENT_ID}`,
    ]);
    expect(revalidatePath).toHaveBeenCalledWith(PAGE);
  });

  it("treats a recipient already gone as removed", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ remove: problemResponse(404) }).fetchImpl);
    await expect(
      removeRecipient(IDLE, form([[RECIPIENT_FIELDS.recipientId, RECIPIENT_ID]])),
    ).rejects.toThrow(`redirect ${PAGE}?removed=1`);
  });

  it("returns any other failure, and refuses a form without an id", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ remove: problemResponse(500) }).fetchImpl);
    const failed = await removeRecipient(
      IDLE,
      form([[RECIPIENT_FIELDS.recipientId, RECIPIENT_ID]]),
    );
    expect(failed.status).toBe("error");
    const stale = await removeRecipient(IDLE, form([]));
    expect(stale).toEqual({
      status: "error",
      formErrors: ["This form is out of date. Reload the page and try again."],
    });
  });
});

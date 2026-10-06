// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { TENANT_HEADER } from "@/server/api/client";
import {
  IDEMPOTENCY_KEY_FIELD,
  IDEMPOTENCY_KEY_HEADER,
  REPLAYED_HEADER,
} from "@/server/api/idempotency";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { CHANGED_VERSION_ID } from "@/test/change-fixture";
import { bulkOutDto } from "@/test/engine-admin-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import { sendChangeCards } from "./actions";
import { BULK_FIELDS } from "./ui/bulk-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const FIRM = "00000000-0000-4000-8000-00000000c0aa";
const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: "00000000-0000-4000-8000-00000000c0ab",
    tenantId: FIRM,
    tenantKind: "ca_firm",
    roles: ["ca_staff"],
    displayName: "Example CA staff",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(ids: readonly string[], key: string | null = FORM_UUID): FormData {
  const data = new FormData();
  for (const id of ids) data.append(BULK_FIELDS.businessId, id);
  if (key !== null) data.set(IDEMPOTENCY_KEY_FIELD, key);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.clearAllMocks();
});

describe("sendChangeCards", () => {
  it("sends the businesses the form named once each, with the form's key, for the firm", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "POST", path: "/v1/notification/bulk", status: 201, body: bulkOutDto() },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await sendChangeCards(
      CHANGED_VERSION_ID,
      IDLE,
      form([REGISTRATION_ID.toUpperCase(), REGISTRATION_ID, ENTITY_ID]),
    );
    expect(state).toMatchObject({
      status: "ok",
      message:
        "Sent. Businesses named: 1. Queued: 1, in 2 cards. Already told: 0. Nobody to tell: 0. Not affected: 0.",
      value: { replayed: false, businesses: [{ businessId: REGISTRATION_ID, outcome: "queued" }] },
    });
    expect(fake.requests[0]?.body).toEqual({
      rule_version_id: CHANGED_VERSION_ID,
      business_ids: [REGISTRATION_ID, ENTITY_ID],
      kind: "change_card",
    });
    expect(fake.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(FIRM);
  });

  it("says a replay of the same request sent nothing twice", async () => {
    await signedInAs({ roles: ["ca_admin"] });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: "/v1/notification/bulk",
          status: 201,
          body: bulkOutDto(),
          headers: { [REPLAYED_HEADER]: "true" },
        },
      ]).fetchImpl,
    );
    const state = await sendChangeCards(CHANGED_VERSION_ID, IDLE, form([REGISTRATION_ID]));
    expect(state).toMatchObject({
      status: "ok",
      value: { replayed: true },
      message: expect.stringMatching(
        /^This request had already been sent, so nothing was sent twice\./,
      ),
    });
  });

  it("says in words that bulk cards are switched off on the service, with its problem", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: "/v1/notification/bulk",
          status: 503,
          problem: {
            type: "urn:compliancewatch:problem:notification-bulk-disabled",
            title: "Example bulk off",
          },
        },
      ]).fetchImpl,
    );
    const state = await sendChangeCards(CHANGED_VERSION_ID, IDLE, form([REGISTRATION_ID]));
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "Example bulk off" },
      formErrors: [expect.stringContaining("switched off on the notification service")],
    });
  });

  it("refuses what it cannot send before any request, and passes another refusal on", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/notification/bulk",
        status: 428,
        problem: {
          type: "urn:compliancewatch:problem:idempotency-key-required",
          title: "Example key missing",
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await sendChangeCards("not-an-id", IDLE, form([REGISTRATION_ID]))).toMatchObject({
      formErrors: ["This is not a rule version id."],
    });
    expect(await sendChangeCards(CHANGED_VERSION_ID, IDLE, form([]))).toMatchObject({
      formErrors: ["The page named no business to tell, or one that is not an id."],
    });
    expect(await sendChangeCards(CHANGED_VERSION_ID, IDLE, form(["nope"]))).toMatchObject({
      formErrors: ["The page named no business to tell, or one that is not an id."],
    });
    const many = Array.from(
      { length: 501 },
      (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    );
    expect(await sendChangeCards(CHANGED_VERSION_ID, IDLE, form(many))).toMatchObject({
      formErrors: ["One change card names at most 500 businesses."],
    });
    expect(fake.requests).toHaveLength(0);
    const keyless = await sendChangeCards(CHANGED_VERSION_ID, IDLE, form([REGISTRATION_ID], null));
    expect(keyless).toMatchObject({ status: "error", problem: { title: "Example key missing" } });
    expect(fake.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBeUndefined();
  });

  it("sends a business tenant's owner to the forbidden page", async () => {
    await signedInAs({ tenantKind: "business", roles: ["owner"] });
    await expect(
      sendChangeCards(CHANGED_VERSION_ID, IDLE, form([REGISTRATION_ID])),
    ).rejects.toThrow("redirect /forbidden");
  });
});

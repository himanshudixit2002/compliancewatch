// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import {
  REVIEWED_TENANT_ID,
  REVIEWER_ID,
  REVIEW_ITEM_ID,
  resolvedItemDto,
} from "@/test/engine-admin-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { resolveReviewItem } from "./actions";
import { RESOLVE_FIELDS } from "./ui/resolve-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const RESOLVE = `/v1/applicability-engine/review-items/${REVIEW_ITEM_ID}/resolve`;

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: REVIEWER_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind: "internal",
    roles,
    displayName: "Example reviewer",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new Error("not found");
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("resolveReviewItem", () => {
  it("settles an item for the looked-up tenant with the session's user as the reviewer", async () => {
    await signedInAs(["reviewer"]);
    const fake = fakeFetch([{ method: "POST", path: RESOLVE, body: resolvedItemDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await resolveReviewItem(
      REVIEWED_TENANT_ID,
      REVIEW_ITEM_ID,
      IDLE,
      form({ [RESOLVE_FIELDS.resolution]: "applies", [RESOLVE_FIELDS.note]: "  Example note  " }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: "Settled: the engine appended a decision that the rule applies.",
    });
    expect(fake.requests[0]?.body).toEqual({
      resolution: "applies",
      note: "Example note",
      resolved_by: REVIEWER_ID,
    });
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(REVIEWED_TENANT_ID);
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/decisions",
    ]);
  });

  it("refuses an analyst, malformed ids and an empty form before any request", async () => {
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await signedInAs(["analyst"]);
    expect(await resolveReviewItem(REVIEWED_TENANT_ID, REVIEW_ITEM_ID, IDLE, form({}))).toEqual({
      status: "error",
      formErrors: ["Only a reviewer or an admin settles a review item."],
    });
    await signedInAs(["admin"]);
    expect(await resolveReviewItem("not-a-tenant", REVIEW_ITEM_ID, IDLE, form({}))).toMatchObject({
      formErrors: ["This is not a tenant's or an item's id."],
    });
    expect(
      await resolveReviewItem(
        REVIEWED_TENANT_ID,
        REVIEW_ITEM_ID,
        IDLE,
        form({ [RESOLVE_FIELDS.note]: " " }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: {
        resolution: ["Choose how to settle the item."],
        note: ["Give a note of 1 to 2000 characters."],
      },
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("passes the engine's refusal of an item already resolved", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: RESOLVE,
          status: 409,
          problem: {
            type: "urn:compliancewatch:problem:applicability-review-item-resolved",
            title: "Example item already resolved",
          },
        },
      ]).fetchImpl,
    );
    const state = await resolveReviewItem(
      REVIEWED_TENANT_ID,
      REVIEW_ITEM_ID,
      IDLE,
      form({ [RESOLVE_FIELDS.resolution]: "dismiss", [RESOLVE_FIELDS.note]: "Example note" }),
    );
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "Example item already resolved" },
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

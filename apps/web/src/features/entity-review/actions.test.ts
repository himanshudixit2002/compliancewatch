// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { REVIEW_TOKEN_HEADER } from "@/server/api/rulebook-write";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import {
  EXAMPLE_ENTITY_ID,
  EXAMPLE_REVIEW_IDS,
  groupDecisionDto,
  reviewItemDto,
} from "@/test/rulebook-fixture";
import { decideEntityGroup } from "./actions";
import { DECISION_FIELDS } from "./ui/decision-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const ANALYST_ID = "00000000-0000-5000-8000-0000000000b1";
const DECISIONS = "/v1/rulebook/review/entities/decisions";
const ITEMS = "/v1/rulebook/review/entities/items";
const GROUP_CLOSED = {
  type: "urn:compliancewatch:problem:rulebook-review-group-closed",
  title: "Example group closed",
};

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: ANALYST_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind: "internal",
    roles,
    displayName: "Example analyst",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string | readonly string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (typeof value === "string") data.set(key, value);
    else for (const one of value) data.append(key, one);
  }
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
  vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new Error("not found");
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  await resetFlagReader();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("decideEntityGroup", () => {
  it("sends the decision with the review token and the session's user, then renders the queue again", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([{ method: "POST", path: DECISIONS, body: groupDecisionDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({
        [DECISION_FIELDS.decision]: "create_entity",
        [DECISION_FIELDS.note]: " Example note ",
        [DECISION_FIELDS.reviewIds]: [EXAMPLE_REVIEW_IDS.first],
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: "Decision recorded. Mentions closed: 2.",
      value: { entityId: EXAMPLE_ENTITY_ID, itemsClosed: 2, relationTargetsUpdated: 1 },
    });
    expect(fake.requests[0]?.body).toEqual({
      entity_type: "form",
      proposed_name: "EXAMPLE-1",
      decision: "create_entity",
      decided_by: ANALYST_ID,
      note: "Example note",
      review_ids: [EXAMPLE_REVIEW_IDS.first],
    });
    expect(fake.requests[0]?.headers[REVIEW_TOKEN_HEADER]).toBe("example-review-token");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/entities",
      "/admin/rulebook/entities/group",
    ]);
  });

  it("rejects with the reason and adds an alias with the entity", async () => {
    await signedInAs(["reviewer"]);
    const fake = fakeFetch([{ method: "POST", path: DECISIONS, body: groupDecisionDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({ decision: "reject", reject_reason: "text_artifact" }),
    );
    await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({ decision: "add_alias", entity_id: EXAMPLE_ENTITY_ID }),
    );
    expect(fake.requests.map((request) => request.body)).toEqual([
      {
        entity_type: "form",
        proposed_name: "EXAMPLE-1",
        decision: "reject",
        reject_reason: "text_artifact",
        decided_by: ANALYST_ID,
        note: "",
      },
      {
        entity_type: "form",
        proposed_name: "EXAMPLE-1",
        decision: "add_alias",
        entity_id: EXAMPLE_ENTITY_ID,
        decided_by: ANALYST_ID,
        note: "",
      },
    ]);
  });

  it("refuses a malformed group and a malformed form before any request", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await decideEntityGroup("example", "x", IDLE, form({ decision: "reject" }))).toEqual({
      status: "error",
      formErrors: ["This group cannot be decided: its type or name is not one the rulebook takes."],
    });
    expect(
      await decideEntityGroup("section", "16(2)", IDLE, form({ decision: "create_entity" })),
    ).toMatchObject({ status: "error", fieldErrors: { decision: [expect.any(String)] } });
    expect(fake.requests).toHaveLength(0);
  });

  it("names the flag when it is off and sends nothing", async () => {
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "false");
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({ decision: "create_entity" }),
    );
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "The web.admin_rulebook_writes flag is off" },
    });
    expect(fake.requests).toHaveLength(0);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("shows a group decided before this decision arrived as information, read again", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      { method: "POST", path: DECISIONS, status: 409, problem: GROUP_CLOSED },
      { method: "GET", path: ITEMS, body: [] },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({ decision: "create_entity" }),
    );
    expect(state).toEqual({
      status: "ok",
      message:
        "Already decided: no open mention of this group was left when this decision arrived, so nothing was recorded again.",
      value: {
        kind: "already",
        message:
          "Already decided: no open mention of this group was left when this decision arrived, so nothing was recorded again.",
      },
    });
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      `POST ${DECISIONS}`,
      `GET ${ITEMS}`,
    ]);
    expect(new URL(fake.requests[1]?.url ?? "").searchParams.get("proposed_name")).toBe(
      "EXAMPLE-1",
    );
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/entities",
      "/admin/rulebook/entities/group",
    ]);
  });

  it("says the included mentions were decided before when none of them is open now", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: DECISIONS, status: 409, problem: GROUP_CLOSED },
        {
          method: "GET",
          path: ITEMS,
          body: [reviewItemDto({ review_id: EXAMPLE_REVIEW_IDS.second })],
        },
      ]).fetchImpl,
    );
    const state = await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({
        [DECISION_FIELDS.decision]: "reject",
        [DECISION_FIELDS.rejectReason]: "out_of_scope",
        [DECISION_FIELDS.reviewIds]: [EXAMPLE_REVIEW_IDS.first.toUpperCase()],
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: { kind: "already", message: expect.stringMatching(/the mentions you included/) },
    });
  });

  it("passes the refusal on when the group cannot be read again or an included one is open", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: DECISIONS, status: 409, problem: GROUP_CLOSED },
        { method: "GET", path: ITEMS, status: 503, problem: { title: "Example outage" } },
      ]).fetchImpl,
    );
    expect(
      await decideEntityGroup("form", "EXAMPLE-1", IDLE, form({ decision: "create_entity" })),
    ).toMatchObject({ status: "error", problem: { title: "Example group closed" } });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: DECISIONS, status: 409, problem: GROUP_CLOSED },
        { method: "GET", path: ITEMS, body: [reviewItemDto()] },
      ]).fetchImpl,
    );
    expect(
      await decideEntityGroup(
        "form",
        "EXAMPLE-1",
        IDLE,
        form({ decision: "create_entity", review_ids: [EXAMPLE_REVIEW_IDS.first] }),
      ),
    ).toMatchObject({ status: "error", problem: { title: "Example group closed" } });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("passes any other refusal on without reading the group again", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: DECISIONS,
        status: 409,
        problem: {
          type: "urn:compliancewatch:problem:rulebook-entity-type-mismatch",
          title: "Example type mismatch",
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await decideEntityGroup(
      "form",
      "EXAMPLE-1",
      IDLE,
      form({ decision: "add_alias", entity_id: EXAMPLE_ENTITY_ID }),
    );
    expect(state).toMatchObject({ status: "error", problem: { title: "Example type mismatch" } });
    expect(fake.requests).toHaveLength(1);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("sends a tenant role to the not-found page", async () => {
    await signedInAs(["owner"]);
    await expect(
      decideEntityGroup("form", "EXAMPLE-1", IDLE, form({ decision: "create_entity" })),
    ).rejects.toThrow("not found");
  });
});

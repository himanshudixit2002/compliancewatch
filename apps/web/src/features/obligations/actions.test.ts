// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import {
  IDEMPOTENCY_KEY_FIELD,
  IDEMPOTENCY_KEY_HEADER,
  REPLAYED_HEADER,
} from "@/server/api/idempotency";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { BUSINESS_DTO } from "@/test/business-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import {
  ENTITY_ID,
  OBLIGATION_ID,
  REGISTRATION_ID,
  TENANT_ID,
  commentDto,
  dueAt,
  listedObligationDto,
  obligationDto,
  obligationPageDto,
} from "@/test/obligation-fixture";
import {
  assignObligation,
  changeObligationStatus,
  checkFirstObligation,
  commentOnObligation,
  loadCalendarMonth,
} from "./actions";
import { ASSIGN_TO_ME, ASSIGN_TO_NOBODY, TRACKING_FIELDS } from "./ui/tracking-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const USER = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";
const ONE = `/v1/obligation/obligations/${OBLIGATION_ID}`;

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: USER,
    tenantId: TENANT_ID,
    tenantKind: "business",
    roles: ["staff"],
    displayName: "Example staff",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  data.set(TRACKING_FIELDS.businessId, ENTITY_ID);
  data.set(TRACKING_FIELDS.obligationId, OBLIGATION_ID);
  data.set(IDEMPOTENCY_KEY_FIELD, FORM_UUID);
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
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.clearAllMocks();
});

describe("changeObligationStatus", () => {
  it("starts an obligation with the form's key and renders its pages again", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "POST", path: `${ONE}/status`, body: obligationDto({ status: "in_progress" }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeObligationStatus(IDLE, form({ [TRACKING_FIELDS.action]: "start" }));
    expect(state).toEqual({
      status: "ok",
      value: { message: "Started: the obligation is in progress.", replayed: false },
      message: "Started: the obligation is in progress.",
    });
    expect(fake.requests[0]?.body).toEqual({ action: "start" });
    expect(fake.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      `/b/${ENTITY_ID}/obligations/${OBLIGATION_ID}`,
      `/b/${ENTITY_ID}/obligations`,
      `/b/${ENTITY_ID}/calendar`,
    ]);
  });

  it("says when the service replayed the first answer to the same request", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: `${ONE}/status`,
          body: obligationDto({ status: "done" }),
          headers: { [REPLAYED_HEADER]: "true" },
        },
      ]).fetchImpl,
    );
    const state = await changeObligationStatus(
      IDLE,
      form({ [TRACKING_FIELDS.action]: "complete" }),
    );
    expect(state.status === "ok" && state.value).toEqual({
      message:
        "Marked as done. This request had already been recorded, so nothing was recorded twice.",
      replayed: true,
    });
  });

  it("refuses a short waiver reason and an unknown action before any call", async () => {
    await signedInAs();
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const short = await changeObligationStatus(
      IDLE,
      form({ [TRACKING_FIELDS.action]: "waive", [TRACKING_FIELDS.reason]: " too short " }),
    );
    expect(short).toEqual({
      status: "error",
      fieldErrors: { [TRACKING_FIELDS.reason]: ["Give a reason of at least 10 characters."] },
    });
    const unknown = await changeObligationStatus(
      IDLE,
      form({ [TRACKING_FIELDS.action]: "reopen" }),
    );
    expect(unknown.status).toBe("error");
    const badIds = await changeObligationStatus(
      IDLE,
      form({ [TRACKING_FIELDS.action]: "start", [TRACKING_FIELDS.obligationId]: "x" }),
    );
    expect(badIds.status).toBe("error");
    expect(fake.requests).toHaveLength(0);
  });

  it("waives with the reason and shows the service's refusal of a closed obligation", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${ONE}/status`,
        status: 409,
        problem: { title: "Example obligation closed", detail: "Example detail" },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeObligationStatus(
      IDLE,
      form({
        [TRACKING_FIELDS.action]: "waive",
        [TRACKING_FIELDS.reason]: "Example reason for the waiver",
      }),
    );
    expect(fake.requests[0]?.body).toEqual({
      action: "waive",
      reason: "Example reason for the waiver",
    });
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "Example obligation closed", detail: "Example detail" },
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("sends a visitor without a session to sign in", async () => {
    await expect(
      changeObligationStatus(IDLE, form({ [TRACKING_FIELDS.action]: "start" })),
    ).rejects.toThrow(/^redirect \/sign-in/);
  });
});

describe("assignObligation", () => {
  it("gives it to the signed-in user for 'me', to nobody, or to a typed id", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "PUT", path: `${ONE}/assignee`, body: obligationDto({ assignee_id: USER }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const me = await assignObligation(IDLE, form({ [TRACKING_FIELDS.assignTo]: ASSIGN_TO_ME }));
    expect(me).toMatchObject({ status: "ok", message: "It is given to you now." });
    await assignObligation(
      IDLE,
      form({ [TRACKING_FIELDS.assignTo]: ASSIGN_TO_NOBODY, [TRACKING_FIELDS.assignee]: USER }),
    );
    await assignObligation(
      IDLE,
      form({ [TRACKING_FIELDS.assignee]: " 00000000-0000-4000-8000-0000000000AC " }),
    );
    expect(fake.requests.map((request) => request.body)).toEqual([
      { assignee_id: USER },
      { assignee_id: null },
      { assignee_id: "00000000-0000-4000-8000-0000000000ac" },
    ]);
  });

  it("words the answer for nobody and for another user", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch([{ method: "PUT", path: `${ONE}/assignee`, body: obligationDto() }]).fetchImpl,
    );
    expect(await assignObligation(IDLE, form({ [TRACKING_FIELDS.assignee]: "" }))).toMatchObject({
      message: "It is given to nobody now.",
    });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "PUT",
          path: `${ONE}/assignee`,
          body: obligationDto({ assignee_id: "00000000-0000-4000-8000-0000000000ac" }),
        },
      ]).fetchImpl,
    );
    expect(
      await assignObligation(
        IDLE,
        form({ [TRACKING_FIELDS.assignee]: "00000000-0000-4000-8000-0000000000ac" }),
      ),
    ).toMatchObject({ message: "It is given to user 00000000-0000-4000-8000-0000000000ac now." });
  });

  it("refuses a value that is not a user id", async () => {
    await signedInAs();
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await assignObligation(IDLE, form({ [TRACKING_FIELDS.assignee]: "Example person" })),
    ).toEqual({
      status: "error",
      fieldErrors: {
        [TRACKING_FIELDS.assignee]: [
          "Enter a user id, such as the one the account page shows, or leave it empty.",
        ],
      },
    });
    expect((await assignObligation(IDLE, form({ [TRACKING_FIELDS.businessId]: "x" }))).status).toBe(
      "error",
    );
    expect(fake.requests).toHaveLength(0);
  });
});

describe("commentOnObligation", () => {
  it("adds a trimmed comment with the form's key", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "POST", path: `${ONE}/comments`, status: 201, body: commentDto() },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await commentOnObligation(
      IDLE,
      form({ [TRACKING_FIELDS.body]: "  Example comment " }),
    );
    expect(state).toMatchObject({ status: "ok", message: "Comment added." });
    expect(fake.requests[0]?.body).toEqual({ body: "Example comment" });
    expect(fake.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);
  });

  it("refuses an empty or a too long comment before any call", async () => {
    await signedInAs();
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await commentOnObligation(IDLE, form({ [TRACKING_FIELDS.body]: "   " }))).toEqual({
      status: "error",
      fieldErrors: { [TRACKING_FIELDS.body]: ["Write the comment first."] },
    });
    expect(
      await commentOnObligation(IDLE, form({ [TRACKING_FIELDS.body]: "x".repeat(2001) })),
    ).toEqual({
      status: "error",
      fieldErrors: { [TRACKING_FIELDS.body]: ["A comment can be at most 2000 characters."] },
    });
    expect(
      (await commentOnObligation(IDLE, form({ [TRACKING_FIELDS.obligationId]: "x" }))).status,
    ).toBe("error");
    expect(fake.requests).toHaveLength(0);
  });
});

describe("checkFirstObligation", () => {
  it("answers the summary's poll for a business id, and refuses anything else", async () => {
    await signedInAs({ roles: ["owner"] });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
        { path: `/v1/businesses/${ENTITY_ID}/obligations`, body: obligationPageDto([]) },
        {
          path: `/v1/businesses/${REGISTRATION_ID}/obligations`,
          body: obligationPageDto([listedObligationDto({ due_at: dueAt("2000-01-20") })]),
        },
      ]).fetchImpl,
    );
    expect(await checkFirstObligation(ENTITY_ID)).toMatchObject({
      status: "found",
      title: "Example return 1",
    });
    expect(await checkFirstObligation("not-an-id")).toEqual({
      status: "error",
      message: "This is not a business id.",
      correlationId: null,
    });
  });
});

describe("loadCalendarMonth", () => {
  it("reads another month for the grid, and refuses a business that is not an id", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
        { path: `/v1/businesses/${ENTITY_ID}/obligations`, body: obligationPageDto([]) },
        {
          path: `/v1/businesses/${REGISTRATION_ID}/obligations`,
          body: obligationPageDto([listedObligationDto({ due_at: dueAt("2000-02-20") })]),
        },
      ]).fetchImpl,
    );
    const answer = await loadCalendarMonth(ENTITY_ID, "2000-02");
    expect(answer.status).toBe("ok");
    if (answer.status !== "ok") return;
    expect(answer.data.month).toEqual({ year: 2000, month: 2 });
    expect(answer.data.total).toBe(1);
    expect(answer.data.selected).toBe("2000-02-20");
    expect(await loadCalendarMonth("x", "2000-02")).toEqual({
      status: "error",
      message: "This is not a business id.",
      correlationId: null,
    });
  });

  it("says what failed when the month could not be read", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { path: `/v1/businesses/${ENTITY_ID}`, status: 503, problem: { title: "Example down" } },
      ]).fetchImpl,
    );
    expect(await loadCalendarMonth(ENTITY_ID, "2000-02")).toMatchObject({
      status: "error",
      message: "Example down",
    });
  });
});

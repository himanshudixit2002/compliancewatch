// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { encryptSession } from "@/server/session";
import {
  ADMIN_USER_ID,
  RUN_VERSION_ID,
  fanOutRunDto,
  heldDto,
  holdDto,
} from "@/test/engine-admin-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { lifecycleDto } from "@/test/rule-version-fixture";
import { controlFanOut, rollBackVersion, setFanOutHold } from "./actions";
import { CONTROL_FIELDS } from "./ui/controls-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const INTERNAL = "00000000-0000-4000-8000-0000000000ee";
const RUN = `/v1/applicability-engine/fan-outs/${RUN_VERSION_ID}`;
const HOLD = "/v1/applicability-engine/fan-out-hold";
const REASON = "Example reason of enough length";

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: ADMIN_USER_ID,
    tenantId: INTERNAL,
    tenantKind: "internal",
    roles,
    displayName: "Example admin",
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

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  await resetFlagReader();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("setFanOutHold", () => {
  it("sets the hold with the reason and renders the fan-out pages again", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([{ method: "PUT", path: HOLD, body: heldDto(REASON) }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await setFanOutHold(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.hold]: "on", [CONTROL_FIELDS.reason]: `  ${REASON}  ` }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: { message: expect.stringMatching(/^The hold is set/) },
    });
    expect(fake.requests[0]?.body).toEqual({ held: true, reason: REASON });
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/fan-outs",
      `/admin/fan-outs/${RUN_VERSION_ID}`,
    ]);
  });

  it("releases the hold from the list with a reason too", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([{ method: "PUT", path: HOLD, body: holdDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await setFanOutHold(
      null,
      IDLE,
      form({ [CONTROL_FIELDS.hold]: "off", [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(state.status).toBe("ok");
    expect(fake.requests[0]?.body).toEqual({ held: false, reason: REASON });
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual(["/admin/fan-outs"]);
  });

  it("refuses anyone but an admin, a short reason and an unknown control before any request", async () => {
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await signedInAs(["reviewer"]);
    expect(
      await setFanOutHold(
        null,
        IDLE,
        form({ [CONTROL_FIELDS.hold]: "on", [CONTROL_FIELDS.reason]: REASON }),
      ),
    ).toEqual({ status: "error", formErrors: ["Only an admin controls fan-outs."] });
    await signedInAs(["admin"]);
    expect(
      await setFanOutHold(
        null,
        IDLE,
        form({ [CONTROL_FIELDS.hold]: "on", [CONTROL_FIELDS.reason]: "Too short" }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { reason: ["Give a reason of at least 10 characters."] },
    });
    expect(
      await setFanOutHold(
        null,
        IDLE,
        form({ [CONTROL_FIELDS.hold]: "maybe", [CONTROL_FIELDS.reason]: REASON }),
      ),
    ).toMatchObject({ status: "error", formErrors: ["This is not a control the page offers."] });
    expect(
      await setFanOutHold("not-an-id", IDLE, form({ [CONTROL_FIELDS.hold]: "on" })),
    ).toMatchObject({ status: "error", formErrors: ["This is not a rule version id."] });
    expect(
      await setFanOutHold(
        null,
        IDLE,
        form({ [CONTROL_FIELDS.hold]: "on", [CONTROL_FIELDS.reason]: "x".repeat(2001) }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { reason: ["Keep the reason to 2000 characters."] },
    });
    expect(fake.requests).toHaveLength(0);
  });
});

describe("controlFanOut", () => {
  it("pauses and cancels with a reason, resumes without one", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      { method: "POST", path: `${RUN}/pause`, body: fanOutRunDto({ status: "paused" }) },
      { method: "POST", path: `${RUN}/resume`, body: fanOutRunDto() },
      { method: "POST", path: `${RUN}/cancel`, body: fanOutRunDto({ status: "cancelled" }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const paused = await controlFanOut(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.control]: "pause", [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(paused).toMatchObject({ status: "ok", message: expect.stringMatching(/^Paused/) });
    const resumed = await controlFanOut(
      RUN_VERSION_ID.toUpperCase(),
      IDLE,
      form({ [CONTROL_FIELDS.control]: "resume" }),
    );
    expect(resumed).toMatchObject({ status: "ok", message: expect.stringMatching(/^Resumed/) });
    const cancelled = await controlFanOut(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.control]: "cancel", [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(cancelled).toMatchObject({ status: "ok", message: expect.stringMatching(/^Cancelled/) });
    expect(fake.requests.map((request) => [request.pathname, request.body])).toEqual([
      [`${RUN}/pause`, { reason: REASON }],
      [`${RUN}/resume`, { reason: "" }],
      [`${RUN}/cancel`, { reason: REASON }],
    ]);
  });

  it("refuses a pause without a reason and passes the engine's refusal on", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${RUN}/cancel`,
        status: 409,
        problem: {
          type: "urn:compliancewatch:problem:applicability-fan-out-state",
          title: "Example run has finished",
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await controlFanOut(RUN_VERSION_ID, IDLE, form({ [CONTROL_FIELDS.control]: "pause" })),
    ).toEqual({
      status: "error",
      fieldErrors: { reason: ["Give a reason of at least 10 characters."] },
    });
    expect(
      await controlFanOut(RUN_VERSION_ID, IDLE, form({ [CONTROL_FIELDS.control]: "stop" })),
    ).toMatchObject({ formErrors: ["This is not a control the page offers."] });
    const refused = await controlFanOut(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.control]: "cancel", [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(refused).toMatchObject({
      status: "error",
      problem: { title: "Example run has finished" },
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("refuses a reviewer and a malformed id", async () => {
    vi.stubGlobal("fetch", fakeFetch([]).fetchImpl);
    await signedInAs(["reviewer"]);
    expect(
      await controlFanOut(RUN_VERSION_ID, IDLE, form({ [CONTROL_FIELDS.control]: "resume" })),
    ).toMatchObject({ formErrors: ["Only an admin controls fan-outs."] });
    await signedInAs(["admin"]);
    expect(
      await controlFanOut("not-an-id", IDLE, form({ [CONTROL_FIELDS.control]: "resume" })),
    ).toMatchObject({ formErrors: ["This is not a rule version id."] });
  });
});

describe("rollBackVersion", () => {
  it("withdraws the version through the rulebook with the reason, as the session's user", async () => {
    vi.stubEnv("CW_WEB_FLAG_PUBLISH_ACTIONS", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: `/v1/rulebook/rule-versions/${RUN_VERSION_ID}/withdraw`,
        body: lifecycleDto({ rule_version_id: RUN_VERSION_ID, status: "withdrawn" }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await rollBackVersion(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(state).toMatchObject({ status: "ok", message: expect.stringMatching(/^Withdrawn/) });
    expect(fake.requests[0]?.headers["x-cw-review-token"]).toBe("example-review-token");
    expect(fake.requests[0]?.body).toMatchObject({ actor_id: ADMIN_USER_ID, note: REASON });
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      `/admin/rulebook/versions/${RUN_VERSION_ID}`,
      "/admin/rulebook/versions",
      "/admin/fan-outs",
      `/admin/fan-outs/${RUN_VERSION_ID}`,
    ]);
  });

  it("is refused with the flag off, without a request, and needs a reason", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await rollBackVersion(RUN_VERSION_ID, IDLE, form({}))).toEqual({
      status: "error",
      fieldErrors: { reason: ["Give a reason of at least 10 characters."] },
    });
    const off = await rollBackVersion(
      RUN_VERSION_ID,
      IDLE,
      form({ [CONTROL_FIELDS.reason]: REASON }),
    );
    expect(off).toMatchObject({
      status: "error",
      problem: { title: expect.stringContaining("web.publish_actions") },
    });
    expect(fake.requests).toHaveLength(0);
    await signedInAs(["reviewer"]);
    expect(
      await rollBackVersion(RUN_VERSION_ID, IDLE, form({ [CONTROL_FIELDS.reason]: REASON })),
    ).toMatchObject({ formErrors: ["Only an admin controls fan-outs."] });
    expect(
      await rollBackVersion("not-an-id", IDLE, form({ [CONTROL_FIELDS.reason]: REASON })),
    ).toMatchObject({ formErrors: ["Only an admin controls fan-outs."] });
  });
});

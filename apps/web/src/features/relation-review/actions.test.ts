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
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_RULE_RELATION_ID,
  approvalDto,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { EXAMPLE_OTHER_VERSION_ID, EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { approveCandidate, rejectCandidate } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const ANALYST_ID = "00000000-0000-5000-8000-0000000000b1";
const APPROVE = `/v1/rulebook/review/relations/${EXAMPLE_CANDIDATE_ID}/approve`;
const REJECT = `/v1/rulebook/review/relations/${EXAMPLE_CANDIDATE_ID}/reject`;
const LIST = "/v1/rulebook/review/relations";
const CANDIDATE_CLOSED = {
  type: "urn:compliancewatch:problem:rulebook-relation-candidate-closed",
  title: "Example candidate closed",
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

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
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

describe("approveCandidate", () => {
  it("approves from the draft onto the version with the review token and the session's user", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([{ method: "POST", path: APPROVE, body: approvalDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
      true,
      IDLE,
      form({
        from_rule_version_id: EXAMPLE_VERSION_ID,
        target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        note: " Example note ",
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: `Approved: rule relation ${EXAMPLE_RULE_RELATION_ID} recorded.`,
      value: {
        ruleRelationId: EXAMPLE_RULE_RELATION_ID,
        graphHref: `/admin/rulebook/relations/graph?rule_version_id=${EXAMPLE_VERSION_ID}`,
      },
    });
    expect(fake.requests[0]?.body).toEqual({
      from_rule_version_id: EXAMPLE_VERSION_ID,
      target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
      decided_by: ANALYST_ID,
      note: "Example note",
    });
    expect(fake.requests[0]?.headers[REVIEW_TOKEN_HEADER]).toBe("example-review-token");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/relations",
      `/admin/rulebook/relations/${EXAMPLE_CANDIDATE_ID}`,
    ]);
  });

  it("asks for the affected version before any request where the candidate needs one", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        true,
        IDLE,
        form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { target_rule_version_id: ["Choose the version this relation points at."] },
    });
    expect(await approveCandidate("not-an-id", false, IDLE, form({}))).toEqual({
      status: "error",
      formErrors: ["This is not a candidate's id."],
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("passes the rulebook's refusal of a closed draft on", async () => {
    await signedInAs(["reviewer"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: APPROVE,
          status: 409,
          problem: {
            type: "urn:compliancewatch:problem:rulebook-rule-version-closed",
            title: "Example draft closed",
          },
        },
      ]).fetchImpl,
    );
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
      false,
      IDLE,
      form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
    );
    expect(state).toMatchObject({ status: "error", problem: { title: "Example draft closed" } });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("a decision the rulebook found already made", () => {
  it("reads the candidate again and shows the analyst's own approval as information", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      { method: "POST", path: APPROVE, status: 409, problem: CANDIDATE_CLOSED },
      {
        method: "GET",
        path: LIST,
        body: [relationCandidateDto({ status: "approved", decided_by: ANALYST_ID })],
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
      false,
      IDLE,
      form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
    );
    const message =
      "Already decided: this candidate was approved by you before this decision arrived, so nothing was recorded again.";
    expect(state).toEqual({
      status: "ok",
      message,
      value: { kind: "already", message, ruleRelationId: null, graphHref: null },
    });
    const read = new URL(fake.requests[1]?.url ?? "");
    expect(read.pathname).toBe(LIST);
    expect(read.searchParams.get("status")).toBe("approved");
    expect(read.searchParams.get("limit")).toBe("1");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/relations",
      `/admin/rulebook/relations/${EXAMPLE_CANDIDATE_ID}`,
    ]);
  });

  it("names who rejected it, and why", async () => {
    await signedInAs(["analyst"]);
    const other = "00000000-0000-5000-8000-0000000000b2";
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: REJECT, status: 409, problem: CANDIDATE_CLOSED },
        {
          method: "GET",
          path: LIST,
          body: [
            relationCandidateDto({
              status: "rejected",
              decided_by: other,
              reject_reason: "not_in_text",
            }),
          ],
        },
      ]).fetchImpl,
    );
    const state = await rejectCandidate(EXAMPLE_CANDIDATE_ID, IDLE, form({ reason: "duplicate" }));
    expect(state).toMatchObject({
      status: "ok",
      message: `Already decided: this candidate was rejected by ${other} (Not in the text) before this decision arrived, so nothing was recorded again.`,
    });
  });

  it("passes the refusal on when the candidate cannot be read again or is still open", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: REJECT, status: 409, problem: CANDIDATE_CLOSED },
        { method: "GET", path: LIST, status: 503, problem: { title: "Example outage" } },
      ]).fetchImpl,
    );
    expect(
      await rejectCandidate(EXAMPLE_CANDIDATE_ID, IDLE, form({ reason: "duplicate" })),
    ).toMatchObject({ status: "error", problem: { title: "Example candidate closed" } });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: REJECT, status: 409, problem: CANDIDATE_CLOSED },
        { method: "GET", path: LIST, body: [relationCandidateDto()] },
      ]).fetchImpl,
    );
    expect(
      await rejectCandidate(EXAMPLE_CANDIDATE_ID, IDLE, form({ reason: "duplicate" })),
    ).toMatchObject({ status: "error", problem: { title: "Example candidate closed" } });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("rejectCandidate", () => {
  it("rejects with the reason and the session's user", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: REJECT,
        body: relationCandidateDto({ status: "rejected", reject_reason: "not_in_text" }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await rejectCandidate(
      EXAMPLE_CANDIDATE_ID,
      IDLE,
      form({ reason: "not_in_text", note: "Example note" }),
    );
    expect(state).toMatchObject({ status: "ok", message: "Rejected: Not in the text." });
    expect(fake.requests[0]?.body).toEqual({
      reason: "not_in_text",
      decided_by: ANALYST_ID,
      note: "Example note",
    });
  });

  it("names the flag when it is off and sends nothing", async () => {
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "false");
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await rejectCandidate(EXAMPLE_CANDIDATE_ID, IDLE, form({ reason: "duplicate" }));
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "The web.admin_rulebook_writes flag is off" },
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("asks for a reason before any request", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await rejectCandidate(EXAMPLE_CANDIDATE_ID, IDLE, form({}))).toEqual({
      status: "error",
      fieldErrors: { reason: ["Choose why the candidate is rejected."] },
    });
    expect(fake.requests).toHaveLength(0);
  });
});

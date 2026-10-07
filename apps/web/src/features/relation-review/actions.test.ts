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
import { fakeFetch, jsonResponse, problemResponse, type FakeRoute } from "@/test/fake-fetch";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_RULE_RELATION_ID,
  approvalDto,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  ruleDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
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

/** A version of another rule, which the candidate (naming example_rule) may not point at. */
const STRANGER_VERSION_ID = "00000000-0000-4000-8000-0000000000f9";

/**
 * The reads an approval makes before it sends anything: the candidate (open unless said
 * otherwise), the rules, and each rule's versions (a draft and a published version of
 * example_rule, a draft of another rule).
 */
function reads(candidate = relationCandidateDto()): FakeRoute[] {
  return [
    { method: "GET", path: LIST, body: [candidate] },
    {
      method: "GET",
      path: "/v1/rulebook/rules",
      body: [ruleDto(), ruleDto({ rule_key: "example_other" })],
    },
    {
      method: "GET",
      path: "/v1/rulebook/rules/example_rule/versions",
      body: [
        ruleVersionDto(),
        ruleVersionDto({
          rule_version_id: EXAMPLE_OTHER_VERSION_ID,
          version: 2,
          status: "published",
        }),
      ],
    },
    {
      method: "GET",
      path: "/v1/rulebook/rules/example_other/versions",
      body: [ruleVersionDto({ rule_version_id: STRANGER_VERSION_ID, rule_key: "example_other" })],
    },
  ];
}

function posts(requests: { method: string }[]): number {
  return requests.filter((request) => request.method === "POST").length;
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
    const fake = fakeFetch([...reads(), { method: "POST", path: APPROVE, body: approvalDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
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
    const sent = fake.requests.find((request) => request.method === "POST");
    expect(sent?.body).toEqual({
      from_rule_version_id: EXAMPLE_VERSION_ID,
      target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
      decided_by: ANALYST_ID,
      note: "Example note",
    });
    expect(sent?.headers[REVIEW_TOKEN_HEADER]).toBe("example-review-token");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/relations",
      `/admin/rulebook/relations/${EXAMPLE_CANDIDATE_ID}`,
    ]);
  });

  it("refuses a target or a draft the page did not offer, and sends nothing", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([...reads(), { method: "POST", path: APPROVE, body: approvalDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    // A version of another rule than the one the candidate names.
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({
          from_rule_version_id: EXAMPLE_VERSION_ID,
          target_rule_version_id: STRANGER_VERSION_ID,
        }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: {
        target_rule_version_id: ["Choose one of the versions offered for this candidate."],
      },
    });
    // A published version is not a draft a relation may start from.
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({
          from_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
          target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { from_rule_version_id: ["Choose one of the open drafts offered."] },
    });
    expect(posts(fake.requests)).toBe(0);
  });

  it("asks for the version a candidate needs, read from the rulebook, and checks the shape first", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch(reads());
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { target_rule_version_id: ["Choose the version this relation points at."] },
    });
    expect(posts(fake.requests)).toBe(0);
    const readsBefore = fake.requests.length;
    expect(await approveCandidate("not-an-id", IDLE, form({}))).toEqual({
      status: "error",
      formErrors: ["This is not a candidate's id."],
    });
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({ from_rule_version_id: "not-a-version" }),
      ),
    ).toMatchObject({
      status: "error",
      fieldErrors: { from_rule_version_id: [expect.any(String)] },
    });
    expect(fake.requests).toHaveLength(readsBefore);
  });

  it("says plainly that the candidate is gone, and passes a failed read on", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal("fetch", fakeFetch([{ method: "GET", path: LIST, body: [] }]).fetchImpl);
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
      ),
    ).toEqual({
      status: "error",
      formErrors: ["The rulebook holds no such candidate any more: nothing was recorded."],
    });
    vi.stubGlobal(
      "fetch",
      fakeFetch([{ method: "GET", path: LIST, status: 503, problem: { title: "Example outage" } }])
        .fetchImpl,
    );
    expect(
      await approveCandidate(
        EXAMPLE_CANDIDATE_ID,
        IDLE,
        form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
      ),
    ).toMatchObject({ status: "error", problem: { title: "Example outage" } });
  });

  it("passes the rulebook's refusal of a closed draft on", async () => {
    await signedInAs(["reviewer"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        ...reads(relationCandidateDto({ relation: "refers_to", target_rule_key: null })),
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
      IDLE,
      form({ from_rule_version_id: EXAMPLE_VERSION_ID }),
    );
    expect(state).toMatchObject({ status: "error", problem: { title: "Example draft closed" } });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("a decision the rulebook found already made", () => {
  it("says the analyst's own approval found on the read before sending, as information", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      ...reads(relationCandidateDto({ status: "approved", decided_by: ANALYST_ID })),
      { method: "POST", path: APPROVE, body: approvalDto() },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
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
    expect(posts(fake.requests)).toBe(0);
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/rulebook/relations",
      `/admin/rulebook/relations/${EXAMPLE_CANDIDATE_ID}`,
    ]);
  });

  it("reads a candidate decided between the read and the approval again, and says who decided", async () => {
    await signedInAs(["analyst"]);
    let listReads = 0;
    const versions = reads().slice(1);
    const fake = fakeFetch((request) => {
      if (request.method === "GET" && request.pathname === LIST) {
        listReads += 1;
        return jsonResponse(200, [
          relationCandidateDto(
            listReads === 1 ? {} : { status: "approved", decided_by: ANALYST_ID },
          ),
        ]);
      }
      if (request.method === "POST") return problemResponse(409, CANDIDATE_CLOSED);
      const route = versions.find((candidate) => candidate.path === request.pathname);
      return route === undefined ? problemResponse(404) : jsonResponse(200, route.body);
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await approveCandidate(
      EXAMPLE_CANDIDATE_ID,
      IDLE,
      form({
        from_rule_version_id: EXAMPLE_VERSION_ID,
        target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: { kind: "already" },
      message: expect.stringContaining("approved by you") as string,
    });
    const reread = new URL(
      fake.requests.filter((request) => request.pathname === LIST).at(-1)?.url ?? "",
    );
    expect(reread.searchParams.get("status")).toBe("approved");
    expect(reread.searchParams.get("limit")).toBe("1");
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

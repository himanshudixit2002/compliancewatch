// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { REVIEW_TOKEN_HEADER } from "@/server/api/rulebook-write";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import {
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  lifecycleDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  EXAMPLE_CANDIDATE_TASK_ID,
  EXAMPLE_NEXT_TASK_ID,
  EXAMPLE_RELATION_CANDIDATE_ID,
  EXAMPLE_TASK_ID,
  candidateTaskDetailDto,
  reviewTaskDetailDto,
  reviewTaskDto,
  seedTasksDto,
  taskDecisionDto,
} from "@/test/review-task-fixture";
import { relationField } from "./ui/form-shared";
import {
  claimFromQueue,
  claimTask,
  decideTask,
  draftFromCandidate,
  editDraft,
  openSeedTasks,
} from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const USER_ID = "00000000-0000-5000-8000-0000000000b9";
const TASK = `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`;
const CANDIDATE_TASK = `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`;

function problem(slug: string, status: number, detail?: string) {
  return {
    status,
    problem: {
      type: `${PROBLEM_TYPE_PREFIX}${slug}`,
      title: `Example ${slug}`,
      ...(detail === undefined ? {} : { detail }),
    },
  };
}

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: USER_ID,
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

function paths(): unknown[] {
  return vi.mocked(revalidatePath).mock.calls.map(([path]) => path);
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

describe("claimTask and claimFromQueue", () => {
  it("claims the task as the session's user with the review token and renders the queue again", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${TASK}/claim`,
        body: reviewTaskDto({ status: "claimed", claimed_by: USER_ID }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await claimTask(EXAMPLE_TASK_ID.toUpperCase())).toMatchObject({
      status: "ok",
      message: "The task is yours: draft or edit it, then decide.",
      value: { kind: "done", links: [{ href: `/admin/review/${EXAMPLE_TASK_ID}` }] },
    });
    expect(fake.requests[0]?.body).toEqual({ actor_id: USER_ID });
    expect(fake.requests[0]?.headers[REVIEW_TOKEN_HEADER]).toBe("example-review-token");
    expect(paths()).toEqual([
      "/admin/review",
      "/admin/review/stats",
      `/admin/review/${EXAMPLE_TASK_ID}`,
    ]);
  });

  it("claims a queue row's task, and refuses an id that is not one before any request", async () => {
    await signedInAs(["reviewer"]);
    const fake = fakeFetch([{ method: "POST", path: `${TASK}/claim`, body: reviewTaskDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect((await claimFromQueue(IDLE, form({ task_id: EXAMPLE_TASK_ID }))).status).toBe("ok");
    expect(await claimFromQueue(IDLE, form({ task_id: "nope" }))).toEqual({
      status: "error",
      formErrors: ["This is not a review task's id."],
    });
    expect(await claimTask("nope")).toEqual({
      status: "error",
      formErrors: ["This is not a review task's id."],
    });
    expect(fake.requests).toHaveLength(1);
  });

  it("names who holds a task someone else claimed, read again", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      { method: "POST", path: `${TASK}/claim`, ...problem("rulebook-review-task-claimed", 409) },
      {
        method: "GET",
        path: TASK,
        body: reviewTaskDetailDto({
          task: reviewTaskDto({
            status: "claimed",
            claimed_by: EXAMPLE_OTHER_ANALYST_ID,
            claimed_at: "2000-05-01T05:00:00Z",
          }),
        }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await claimTask(EXAMPLE_TASK_ID)).toMatchObject({
      status: "error",
      problem: {
        title: `Claimed by ${EXAMPLE_OTHER_ANALYST_ID} on 1 May 2000, 10:30 am IST: they decide it, or a reviewer returns it to the queue`,
        correlationId: expect.any(String) as string,
      },
    });
  });

  it("refuses without a request while the flag is off", async () => {
    await signedInAs(["analyst"]);
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "false");
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await claimTask(EXAMPLE_TASK_ID)).toMatchObject({
      status: "error",
      problem: { title: "The web.admin_rulebook_writes flag is off" },
    });
    expect(fake.requests).toHaveLength(0);
  });
});

describe("openSeedTasks", () => {
  it("says how many tasks it opened, or that every draft already has one", async () => {
    await signedInAs(["analyst"]);
    let opened = 2;
    const fake = fakeFetch(
      () =>
        new Response(JSON.stringify(seedTasksDto({ opened, task_ids: [] })), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await openSeedTasks()).toMatchObject({
      status: "ok",
      message: "Review tasks opened for seed drafts: 2.",
    });
    opened = 0;
    expect(await openSeedTasks()).toMatchObject({
      message: "Every seed draft that needs review already has a task: nothing was opened.",
    });
    expect(fake.requests[0]).toMatchObject({
      method: "POST",
      pathname: "/v1/rulebook/review/tasks/seed",
    });
    expect(paths()).toContain("/admin/review");
  });

  it("passes the rulebook's refusal on in plain words", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: "/v1/rulebook/review/tasks/seed",
          ...problem("rulebook-reviews-disabled", 503),
        },
      ]).fetchImpl,
    );
    expect(await openSeedTasks()).toMatchObject({
      status: "error",
      problem: { title: "Reviews are switched off on the rulebook" },
    });
  });
});

describe("draftFromCandidate", () => {
  const base = (values: Record<string, string>) => {
    const data = form({ rule_key: "example_rule", citations_mode: "candidate", ...values });
    data.set("base:edits.title", "Example candidate title");
    data.set("edits.title", values["edits.title"] ?? "Example candidate title");
    return data;
  };

  /**
   * The reads the action makes to check the relations it is sent: the task (its candidate's
   * document), the document's open relation candidates, and the versions they may point at (a
   * supersession naming example_rule, whose versions are a draft and a published one).
   */
  const offered = [
    { method: "GET", path: CANDIDATE_TASK, body: candidateTaskDetailDto() },
    {
      method: "GET",
      path: "/v1/rulebook/review/relations",
      body: [
        relationCandidateDto({
          candidate_id: EXAMPLE_RELATION_CANDIDATE_ID,
          relation: "supersedes",
          target_rule_key: "example_rule",
        }),
      ],
    },
    {
      method: "GET",
      path: "/v1/rulebook/rules/example_rule/versions",
      body: [
        ruleVersionDto(),
        ruleVersionDto({ rule_version_id: EXAMPLE_OTHER_VERSION_ID, version: 2 }),
      ],
    },
  ];

  it("drafts the version and says which, with the relations taken on and the clauses cited", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      ...offered,
      {
        method: "POST",
        path: `${CANDIDATE_TASK}/draft`,
        body: candidateTaskDetailDto({
          rule_version: reviewTaskDetailDto().rule_version,
          citations: reviewTaskDetailDto().citations,
        }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await draftFromCandidate(
      EXAMPLE_CANDIDATE_TASK_ID,
      IDLE,
      base({
        "edits.title": "Example edited title",
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on",
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: EXAMPLE_OTHER_VERSION_ID,
        note: "Example why",
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: "Drafted example_rule v1 from the candidate.",
      value: { details: ["Relation candidates taken on: 1.", "Clauses cited: 1."] },
    });
    // The relation reads stay with the candidate's document and the rule the candidate names.
    expect(
      fake.requests
        .filter((request) => request.method === "GET")
        .map((request) => request.pathname),
    ).toEqual([
      CANDIDATE_TASK,
      "/v1/rulebook/review/relations",
      "/v1/rulebook/rules/example_rule/versions",
    ]);
    expect(new URL(fake.requests[1]?.url ?? "").searchParams.get("document_id")).toBe(
      EXAMPLE_DOCUMENT_ID,
    );
    expect(fake.requests.at(-1)?.body).toEqual({
      actor_id: USER_ID,
      rule_key: "example_rule",
      edits: { title: "Example edited title" },
      relation_candidates: [
        {
          candidate_id: EXAMPLE_RELATION_CANDIDATE_ID,
          target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        },
      ],
      note: "Example why",
    });
  });

  it("refuses a relation candidate or a version the page did not offer, and sends nothing", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      ...offered,
      { method: "POST", path: `${CANDIDATE_TASK}/draft`, body: candidateTaskDetailDto() },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const stranger = "00000000-0000-4000-8000-0000000000f9";
    expect(
      await draftFromCandidate(
        EXAMPLE_CANDIDATE_TASK_ID,
        IDLE,
        base({
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on",
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: stranger,
          [relationField(EXAMPLE_NEXT_TASK_ID, "take")]: "on",
        }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: {
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: [
          "Choose one of the versions offered for this relation.",
        ],
        [relationField(EXAMPLE_NEXT_TASK_ID, "take")]: [
          "This relation candidate is not open on the candidate's document any more: untick it.",
        ],
      },
    });
    expect(
      await draftFromCandidate(
        EXAMPLE_CANDIDATE_TASK_ID,
        IDLE,
        base({ [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on" }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: {
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: [
          "Choose the version this relation points at.",
        ],
      },
    });
    expect(fake.requests.filter((request) => request.method === "POST")).toHaveLength(0);
  });

  it("puts the rulebook's field errors on the relation's row", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        ...offered,
        {
          method: "POST",
          path: `${CANDIDATE_TASK}/draft`,
          status: 422,
          problem: {
            type: `${PROBLEM_TYPE_PREFIX}validation-error`,
            title: "Example validation",
            errors: [
              {
                loc: ["body", "relation_candidates", 0, "target_rule_version_id"],
                msg: "Example message",
                type: "value_error",
              },
            ],
          },
        },
      ]).fetchImpl,
    );
    expect(
      await draftFromCandidate(
        EXAMPLE_CANDIDATE_TASK_ID,
        IDLE,
        base({
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on",
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: EXAMPLE_VERSION_ID,
        }),
      ),
    ).toMatchObject({
      status: "error",
      fieldErrors: {
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: ["Example message"],
      },
    });
  });

  it("names the fields out of shape before any request", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await draftFromCandidate(EXAMPLE_CANDIDATE_TASK_ID, IDLE, base({ rule_key: "Not A Key" })),
    ).toMatchObject({ status: "error", fieldErrors: { rule_key: [expect.any(String)] } });
    expect(await draftFromCandidate("nope", IDLE, base({}))).toEqual({
      status: "error",
      formErrors: ["This is not a review task's id."],
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("lists every problem of an incomplete draft, and renders the page again for one drafted already", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: `${CANDIDATE_TASK}/draft`,
          ...problem("rulebook-draft-incomplete", 422, "title: missing; recurrence: unreadable"),
        },
      ]).fetchImpl,
    );
    expect(await draftFromCandidate(EXAMPLE_CANDIDATE_TASK_ID, IDLE, base({}))).toMatchObject({
      status: "error",
      problem: { title: "The draft is incomplete" },
      formErrors: ["title: missing", "recurrence: unreadable"],
    });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: `${CANDIDATE_TASK}/draft`,
          ...problem("rulebook-candidate-already-drafted", 409),
        },
      ]).fetchImpl,
    );
    expect(await draftFromCandidate(EXAMPLE_CANDIDATE_TASK_ID, IDLE, base({}))).toMatchObject({
      status: "error",
      problem: { title: "This candidate was drafted already" },
    });
    expect(paths()).toContain(`/admin/review/${EXAMPLE_CANDIDATE_TASK_ID}`);
  });
});

describe("editDraft", () => {
  function edit(values: Record<string, string>): FormData {
    const data = form(values);
    data.set("base:summary", "Example summary.");
    data.set("summary", values.summary ?? "Example summary.");
    return data;
  }

  it("sends the changed fields and the citations, and says what it saved", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      { method: "PATCH", path: `${TASK}/draft`, body: reviewTaskDetailDto() },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await editDraft(
      EXAMPLE_TASK_ID,
      IDLE,
      edit({
        summary: "Example new summary.",
        "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
        "citations.0.quote": "Example clause text",
      }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: "The draft is saved.",
      value: {
        details: [
          "Changed: Summary.",
          "Citations added: 1; the rulebook found every quote in its clause.",
        ],
      },
    });
    expect(fake.requests[0]?.body).toEqual({
      actor_id: USER_ID,
      summary: "Example new summary.",
      citations: [{ clause_id: EXAMPLE_CLAUSE_IDS.first, quote: "Example clause text" }],
      note: "",
    });
  });

  it("says nothing changed without a request, and passes a quote the rulebook did not find on", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      {
        method: "PATCH",
        path: `${TASK}/draft`,
        ...problem("rulebook-citation-not-verified", 422, "Example quote not in en.p1"),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await editDraft(EXAMPLE_TASK_ID, IDLE, edit({}))).toEqual({
      status: "error",
      formErrors: ["Nothing changed: change a field or add a citation, then save."],
    });
    expect(fake.requests).toHaveLength(0);
    expect(
      await editDraft(EXAMPLE_TASK_ID, IDLE, edit({ summary: "Example other summary." })),
    ).toMatchObject({
      status: "error",
      problem: { title: "A quote is not in its clause", detail: "Example quote not in en.p1" },
    });
  });

  it("says an edit of a task decided meanwhile is not saved, naming who decided it", async () => {
    await signedInAs(["analyst"]);
    const decided = reviewTaskDetailDto({
      task: reviewTaskDto({
        status: "decided",
        decision: "return",
        decided_by: EXAMPLE_OTHER_ANALYST_ID,
        decided_at: "2000-05-02T06:00:00Z",
        note: "Example rework note",
      }),
    });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "PATCH", path: `${TASK}/draft`, ...problem("rulebook-review-task-closed", 409) },
        { method: "POST", path: `${TASK}/claim`, ...problem("rulebook-review-task-closed", 409) },
        {
          method: "POST",
          path: `${CANDIDATE_TASK}/draft`,
          ...problem("rulebook-review-task-closed", 409),
        },
        { method: "GET", path: TASK, body: decided },
        { method: "GET", path: CANDIDATE_TASK, body: decided },
      ]).fetchImpl,
    );
    const title = `This task was decided already (Returned by ${EXAMPLE_OTHER_ANALYST_ID} on 2 May 2000, 11:30 am IST), so nothing was saved`;
    expect(await editDraft(EXAMPLE_TASK_ID, IDLE, edit({ summary: "Example." }))).toMatchObject({
      status: "error",
      problem: { title, detail: "Note: Example rework note" },
    });
    expect(await claimTask(EXAMPLE_TASK_ID)).toMatchObject({ status: "error", problem: { title } });
    const draft = form({ rule_key: "example_rule", citations_mode: "candidate" });
    expect(await draftFromCandidate(EXAMPLE_CANDIDATE_TASK_ID, IDLE, draft)).toMatchObject({
      status: "error",
      problem: { title },
    });
  });

  it("words the rulebook's content refusal and lists each problem", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "PATCH",
          path: `${TASK}/draft`,
          ...problem(
            "invariant-violation",
            422,
            "specification: example_kind = nowhere: not an option; effective_to must be after effective_from",
          ),
        },
      ]).fetchImpl,
    );
    expect(await editDraft(EXAMPLE_TASK_ID, IDLE, edit({ summary: "Example." }))).toMatchObject({
      status: "error",
      problem: { title: "The rulebook refused the draft's content" },
      formErrors: [
        "specification: example_kind = nowhere: not an option",
        "effective_to must be after effective_from",
      ],
    });
  });

  it("says plainly that the task is not the analyst's", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "PATCH",
          path: `${TASK}/draft`,
          ...problem("rulebook-review-task-not-claimed", 409),
        },
        { method: "GET", path: TASK, body: reviewTaskDetailDto() },
      ]).fetchImpl,
    );
    expect(await editDraft(EXAMPLE_TASK_ID, IDLE, edit({ summary: "Example." }))).toMatchObject({
      status: "error",
      problem: { title: "Claim the task first: only the analyst who claimed it drafts and edits" },
    });
  });
});

describe("decideTask", () => {
  it("approves as a reviewer and links the version's page to publish from", async () => {
    await signedInAs(["reviewer"]);
    const fake = fakeFetch([{ method: "POST", path: `${TASK}/decide`, body: taskDecisionDto() }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await decideTask(
      EXAMPLE_TASK_ID,
      false,
      IDLE,
      form({ decision: "approve", high_impact: "on" }),
    );
    expect(state).toMatchObject({
      status: "ok",
      message: "Approved: the round is complete and the version is approved.",
      value: {
        details: ["Version: Approved.", expect.stringMatching(/^Approved by: /) as string],
        links: [
          {
            href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
            label: "Publish it from the version's page",
          },
        ],
      },
    });
    expect(fake.requests[0]?.body).toEqual({
      actor_id: USER_ID,
      decision: "approve",
      note: "",
      high_impact: true,
    });
  });

  it("says the first of two approvals is recorded and a different reviewer completes the round", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: `${TASK}/decide`,
          body: taskDecisionDto({
            task: reviewTaskDto({ status: "open" }),
            version: lifecycleDto({ approved_by: [USER_ID], required_approvals: 2 }),
          }),
        },
      ]).fetchImpl,
    );
    expect(
      await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "approve" })),
    ).toMatchObject({
      status: "ok",
      message: "Your approval is recorded: 1 of 2 approvals.",
      value: {
        details: [
          "A second, different reviewer completes the round.",
          "Version: In review.",
          "Approved by: you.",
        ],
      },
    });
  });

  it("refuses an analyst's approval before any request, and says a second one by the same reviewer plainly", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      { method: "POST", path: `${TASK}/decide`, ...problem("rulebook-duplicate-approver", 409) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "approve" }))).toEqual({
      status: "error",
      formErrors: ["Approving is a reviewer's or an admin's: you can return or reject."],
    });
    expect(fake.requests).toHaveLength(0);
    await signedInAs(["reviewer"]);
    expect(
      await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "approve" })),
    ).toMatchObject({
      status: "error",
      problem: { title: "A different reviewer must approve" },
    });
  });

  it("returns with a note and links the rework's new task", async () => {
    await signedInAs(["analyst"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: `${TASK}/decide`,
          body: taskDecisionDto({
            task: reviewTaskDto({ status: "decided", decision: "return" }),
            version: lifecycleDto({ status: "draft", approved_by: [] }),
            next_task_id: EXAMPLE_NEXT_TASK_ID,
          }),
        },
      ]).fetchImpl,
    );
    expect(
      await decideTask(
        EXAMPLE_TASK_ID,
        false,
        IDLE,
        form({ decision: "return", note: "Example rework" }),
      ),
    ).toMatchObject({
      status: "ok",
      message: "Returned to draft: the rework has a new task.",
      value: {
        details: ["Version: Draft."],
        links: [{ href: `/admin/review/${EXAMPLE_NEXT_TASK_ID}`, label: "Open the rework's task" }],
      },
    });
    expect(
      await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "return" })),
    ).toMatchObject({ status: "error", fieldErrors: { note: [expect.any(String)] } });
  });

  it("rejects a candidate with its reason and says the candidate's status", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${CANDIDATE_TASK}/decide`,
        body: taskDecisionDto({
          task: reviewTaskDto({
            task_id: EXAMPLE_CANDIDATE_TASK_ID,
            status: "decided",
            decision: "reject",
          }),
          version: null,
          candidate_status: "rejected",
        }),
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await decideTask(
        EXAMPLE_CANDIDATE_TASK_ID,
        true,
        IDLE,
        form({ decision: "reject", note: "Example why", reason: "not_a_rule" }),
      ),
    ).toMatchObject({
      status: "ok",
      message: "Rejected: the task is closed.",
      value: { details: ["Candidate: Rejected."], links: [] },
    });
    expect(fake.requests[0]?.body).toEqual({
      actor_id: USER_ID,
      decision: "reject",
      note: "Example why",
      reason: "not_a_rule",
    });
  });

  it("reads a task decided before the decision arrived again, and says who decided it", async () => {
    await signedInAs(["reviewer"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: `${TASK}/decide`, ...problem("rulebook-review-task-closed", 409) },
        {
          method: "GET",
          path: TASK,
          body: reviewTaskDetailDto({
            task: reviewTaskDto({
              status: "decided",
              decision: "approve",
              decided_by: USER_ID,
              decided_at: "2000-05-02T06:00:00Z",
              note: "Example earlier note",
            }),
          }),
        },
      ]).fetchImpl,
    );
    expect(
      await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "approve" })),
    ).toMatchObject({
      status: "ok",
      message: "Already decided: Approved by you on 2 May 2000, 11:30 am IST.",
      value: { kind: "already", details: ["Note: Example earlier note"] },
    });
    expect(paths()).toContain(`/admin/review/${EXAMPLE_TASK_ID}`);
  });

  it("passes the refusal on when the task cannot be read again", async () => {
    await signedInAs(["reviewer"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: `${TASK}/decide`, ...problem("rulebook-review-task-closed", 409) },
        { method: "GET", path: TASK, status: 500, problem: { title: "Example failure" } },
      ]).fetchImpl,
    );
    expect(
      await decideTask(EXAMPLE_TASK_ID, false, IDLE, form({ decision: "approve" })),
    ).toMatchObject({
      status: "error",
      problem: { title: "Example rulebook-review-task-closed" },
    });
  });
});

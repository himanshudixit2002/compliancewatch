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
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import {
  EXAMPLE_VERSION_ID,
  citationDto,
  lifecycleDto,
  publicationDto,
} from "@/test/rule-version-fixture";
import { saveCitations, takeStep } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const USER = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
const VERSION = `/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`;

class NotFound extends Error {}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: USER,
    tenantId: "00000000-0000-4000-8000-00000000000a",
    tenantKind: "internal",
    roles: ["analyst"],
    displayName: "Example analyst",
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
  for (const [key, value] of Object.entries(values)) data.append(key, value);
  return data;
}

function clauseBody(clauseId: string, ref: string) {
  return {
    clause_id: clauseId,
    document_id: EXAMPLE_DOCUMENT_ID,
    clause_ref: ref,
    ordinal: 1,
    page: 1,
    text: "Example clause text",
    regulator: "Example regulator",
    doc_type: "circular",
    external_ref: "Example 1/2000",
    title: "Example document title",
    url: "https://example.com/example.pdf",
    language: "en",
    published_at: null,
  };
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_PUBLISH_ACTIONS", "true");
  vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
  vi.mocked(notFound).mockImplementation(() => {
    throw new NotFound();
  });
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  await resetFlagReader();
  vi.mocked(notFound).mockReset();
  vi.mocked(redirect).mockReset();
  vi.clearAllMocks();
});

describe("saveCitations", () => {
  it("cites the rows with the review token and renders the version and the list again", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "PUT",
        path: `${VERSION}/citations`,
        body: { added: 1, unchanged: 0, citations: [citationDto()] },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveCitations(
      EXAMPLE_VERSION_ID,
      IDLE,
      form({
        "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
        "citations.0.quote": "Example clause text that opens",
      }),
    );
    expect(state).toEqual({
      status: "ok",
      value: {
        added: 1,
        unchanged: 0,
        verified: [
          {
            clauseRef: "en.p1",
            quote: "Example clause text that opens",
            verified: true,
            matchScore: 0.97,
          },
        ],
      },
      message: "Stored. New citations: 1; already cited: 0. Every quote was found in its clause.",
    });
    expect(fake.requests[0]?.headers[REVIEW_TOKEN_HEADER]).toBe("example-review-token");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
      "/admin/rulebook/versions",
    ]);
  });

  it("refuses a malformed row and a malformed version id before any request", async () => {
    await signedInAs();
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await saveCitations(
        EXAMPLE_VERSION_ID,
        IDLE,
        form({ "citations.0.clause_id": "x", "citations.0.quote": "q" }),
      ),
    ).toEqual({
      status: "error",
      fieldErrors: { "citations.0.clause_id": ["This is not a clause id (a UUID)."] },
    });
    expect(await saveCitations(EXAMPLE_VERSION_ID, IDLE, form({}))).toEqual({
      status: "error",
      formErrors: ["Add at least one citation: a clause id and a quote."],
    });
    expect(await saveCitations("not-a-version", IDLE, form({}))).toEqual({
      status: "error",
      formErrors: ["This is not a rule version id."],
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("puts each quote the rulebook could not find on its row, and lists every failure", async () => {
    await signedInAs();
    const detail = `1 quotes are not in their clause: en.p2 of ${EXAMPLE_DOCUMENT_ID}: score 0.38, missing 2000`;
    const fake = fakeFetch((request: RecordedRequest) => {
      if (request.method === "PUT") {
        return problemResponse(422, {
          type: "urn:compliancewatch:problem:rulebook-citation-not-verified",
          title: "Citation quote not found in its clause",
          detail,
        });
      }
      if (request.pathname === `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`) {
        return jsonResponse(200, clauseBody(EXAMPLE_CLAUSE_IDS.first, "en.p1"));
      }
      if (request.pathname === `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.second}`) {
        return jsonResponse(200, clauseBody(EXAMPLE_CLAUSE_IDS.second, "en.p2"));
      }
      return problemResponse(404);
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveCitations(
      EXAMPLE_VERSION_ID,
      IDLE,
      form({
        "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
        "citations.0.quote": "Example clause text",
        "citations.1.clause_id": EXAMPLE_CLAUSE_IDS.second,
        "citations.1.quote": "Example words the clause does not hold",
      }),
    );
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "Citation quote not found in its clause", detail },
      fieldErrors: { "citations.1.quote": ["Not found in its clause: score 0.38, missing 2000"] },
      formErrors: [`en.p2 of ${EXAMPLE_DOCUMENT_ID}: score 0.38, missing 2000`],
    });
    expect(vi.mocked(revalidatePath)).not.toHaveBeenCalled();
  });

  it("marks the rows whose clause the rulebook does not hold", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "PUT",
        path: `${VERSION}/citations`,
        status: 422,
        problem: {
          type: "urn:compliancewatch:problem:rulebook-clause-not-found",
          title: "Clause not in this document",
          detail: `1 clauses are not stored: ${EXAMPLE_CLAUSE_IDS.second}`,
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveCitations(
      EXAMPLE_VERSION_ID,
      IDLE,
      form({
        "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
        "citations.0.quote": "Example",
        "citations.1.clause_id": EXAMPLE_CLAUSE_IDS.second,
        "citations.1.quote": "Example",
      }),
    );
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { "citations.1.clause_id": ["The rulebook holds no clause with this id."] },
    });
    expect(state.status === "error" && state.formErrors).toBeFalsy();
  });

  it("answers the flag's refusal without a request while web.publish_actions is off", async () => {
    await signedInAs();
    vi.stubEnv("CW_WEB_FLAG_PUBLISH_ACTIONS", "false");
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveCitations(
      EXAMPLE_VERSION_ID,
      IDLE,
      form({ "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first, "citations.0.quote": "Example" }),
    );
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "The web.publish_actions flag is off" },
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("is a 404 to a tenant role", async () => {
    await signedInAs({ tenantKind: "business", roles: ["owner"] });
    await expect(saveCitations(EXAMPLE_VERSION_ID, IDLE, form({}))).rejects.toBeInstanceOf(
      NotFound,
    );
  });
});

describe("takeStep", () => {
  it("submits with the session's user as the actor and the high-impact box", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "POST", path: `${VERSION}/submit`, body: lifecycleDto({ approved_by: [] }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await takeStep(
      EXAMPLE_VERSION_ID.toUpperCase(),
      IDLE,
      form({ step: "submit", note: "Example note", high_impact: "on" }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: {
        step: "submit",
        lifecycle: { status: "in_review", highImpact: true },
        publication: null,
      },
    });
    expect(fake.requests[0]?.pathname).toBe(`${VERSION}/submit`);
    expect(fake.requests[0]?.body).toEqual({
      actor_id: USER,
      high_impact: true,
      note: "Example note",
    });
    expect(vi.mocked(revalidatePath)).toHaveBeenCalledWith(
      `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
    );
  });

  it("sends approve, publish, return and withdraw to their routes, never a synthetic approval", async () => {
    await signedInAs({ roles: ["reviewer"] });
    const fake = fakeFetch([
      { method: "POST", path: `${VERSION}/approve`, body: lifecycleDto() },
      { method: "POST", path: `${VERSION}/publish`, body: publicationDto() },
      { method: "POST", path: `${VERSION}/return`, body: lifecycleDto({ status: "draft" }) },
      { method: "POST", path: `${VERSION}/withdraw`, body: lifecycleDto({ status: "withdrawn" }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "approve", synthetic: "true" }));
    const published = await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "publish" }));
    expect(published).toMatchObject({
      status: "ok",
      value: { publication: { replacements: [{}] } },
    });
    await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "return", note: "Example reason text" }));
    await takeStep(
      EXAMPLE_VERSION_ID,
      IDLE,
      form({ step: "withdraw", note: "Example reason text" }),
    );
    expect(fake.requests.map((request) => request.body)).toEqual([
      { actor_id: USER, note: "" },
      { actor_id: USER, note: "" },
      { actor_id: USER, note: "Example reason text" },
      { actor_id: USER, note: "Example reason text" },
    ]);
  });

  it("refuses an analyst's approval, publication and withdrawal before any request", async () => {
    await signedInAs();
    const fake = fakeFetch([
      { method: "POST", path: `${VERSION}/return`, body: lifecycleDto({ status: "draft" }) },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "approve" }))).toEqual({
      status: "error",
      formErrors: ["Approve is a reviewer's or an admin's step: nothing was sent."],
    });
    expect(await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "publish" }))).toEqual({
      status: "error",
      formErrors: ["Publish is a reviewer's or an admin's step: nothing was sent."],
    });
    expect(
      await takeStep(
        EXAMPLE_VERSION_ID,
        IDLE,
        form({ step: "withdraw", note: "Example reason text" }),
      ),
    ).toMatchObject({ status: "error", formErrors: [expect.stringMatching(/^Withdraw is a/)] });
    expect(fake.requests).toHaveLength(0);
    // Returning stays every regulatory role's step.
    expect(
      await takeStep(
        EXAMPLE_VERSION_ID,
        IDLE,
        form({ step: "return", note: "Example reason text" }),
      ),
    ).toMatchObject({ status: "ok" });
    expect(fake.requests.map((request) => request.pathname)).toEqual([`${VERSION}/return`]);
  });

  it("refuses a return without a reason and an unknown step before any request", async () => {
    await signedInAs();
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(
      await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "return", note: "short" })),
    ).toEqual({
      status: "error",
      fieldErrors: { note: ["Give a reason of at least 10 characters."] },
    });
    expect(await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "delete" }))).toMatchObject({
      status: "error",
    });
    expect(await takeStep("not-a-version", IDLE, form({ step: "approve" }))).toMatchObject({
      status: "error",
      formErrors: ["This is not a rule version id."],
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("returns the rulebook's guard with its title and detail", async () => {
    await signedInAs({ roles: ["admin"] });
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${VERSION}/publish`,
        status: 409,
        problem: {
          type: "urn:compliancewatch:problem:rulebook-citations-missing",
          title: "Rule version needs verified citations",
          detail: "Example version cites no clause",
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await takeStep(EXAMPLE_VERSION_ID, IDLE, form({ step: "publish" }));
    expect(state).toMatchObject({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:rulebook-citations-missing",
        title: "Rule version needs verified citations",
        detail: "Example version cites no clause",
      },
    });
    expect(vi.mocked(revalidatePath)).not.toHaveBeenCalled();
  });
});

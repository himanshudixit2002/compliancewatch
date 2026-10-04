// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import type {
  ApprovalOutDto,
  EntityDecisionOutDto,
  EntityGroupDecision,
  RelationCandidateDto,
} from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { fakeFetch, type FakeFetch } from "@/test/fake-fetch";
import { resetEnvCache } from "../env";
import { resetFlagReader } from "../flags";
import { webError, type ApiError } from "../result";
import { REQUEST_ID_HEADER, TENANT_HEADER, WRITE_TOKEN_HEADER } from "./client";
import {
  REVIEW_TOKEN_HEADER,
  RULEBOOK_WRITES_FLAG,
  RefusedWriteGateway,
  RulebookWriteGateway,
  explainTokenProblem,
  rulebookReviewClient,
  rulebookWriteAccess,
  rulebookWriteClient,
  rulebookWrites,
} from "./rulebook-write";
import type { ClientContext, ClientPrincipal } from "./services";

// Obviously fake values: the module must never put either one in an error or another call.
const WRITE_TOKEN = "example-write-token";
const REVIEW_TOKEN = "example-review-token";

const INTERNAL_TENANT = "00000000-0000-4000-8000-000000000001";
const BUSINESS_TENANT = "00000000-0000-4000-8000-000000000002";
const CANDIDATE_ID = "00000000-0000-4000-8000-0000000000c1";
const DOCUMENT_ID = "00000000-0000-4000-8000-0000000000d1";
const CLAUSE_ID = "00000000-0000-4000-8000-0000000000a1";
const ENTITY_ID = "00000000-0000-4000-8000-0000000000e1";
const FROM_VERSION = "00000000-0000-4000-8000-0000000000f1";
const TARGET_VERSION = "00000000-0000-4000-8000-0000000000f2";
const RELATION_ID = "00000000-0000-4000-8000-0000000000b1";
const REVIEW_IDS = ["00000000-0000-4000-8000-000000000011", "00000000-0000-4000-8000-000000000012"];

const RULEBOOK = "http://localhost:8003";
const DECISIONS = "/v1/rulebook/review/entities/decisions";
const APPROVE = `/v1/rulebook/review/relations/${CANDIDATE_ID}/approve`;
const REJECT = `/v1/rulebook/review/relations/${CANDIDATE_ID}/reject`;

function principal(userId: string, roles: ClientPrincipal["roles"]): ClientPrincipal {
  return { userId, tenantId: INTERNAL_TENANT, tenantKind: "internal", roles };
}

const analyst = principal("example-analyst", ["analyst"]);
const reviewer = principal("example-reviewer", ["reviewer"]);
const admin = principal("example-admin", ["admin"]);
const owner: ClientPrincipal = {
  userId: "example-owner",
  tenantId: BUSINESS_TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

function ctx(session: ClientPrincipal | null, fake: FakeFetch = fakeFetch([])): ClientContext {
  return { session, fetchImpl: fake.fetchImpl };
}

/** The flag on through its override (honoured in test) and the review token configured. */
function allowDecisions(): void {
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
  vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
}

function problemSlug(error: ApiError): string | undefined {
  return error.problem?.type.slice(PROBLEM_TYPE_PREFIX.length);
}

function expectNoToken(error: ApiError): void {
  const text = JSON.stringify(error);
  expect(text).not.toContain(WRITE_TOKEN);
  expect(text).not.toContain(REVIEW_TOKEN);
}

const decided: EntityDecisionOutDto = {
  status: "decided",
  resolution: "alias_added",
  entity_id: ENTITY_ID,
  items_closed: 2,
  relation_targets_updated: 1,
};

function candidateDto(overrides: Partial<RelationCandidateDto> = {}): RelationCandidateDto {
  return {
    candidate_id: CANDIDATE_ID,
    document_id: DOCUMENT_ID,
    relation: "refers_to",
    target_type: "form",
    target_name: "Example form",
    target_entity_id: null,
    target_rule_key: null,
    evidence_clause_id: CLAUSE_ID,
    evidence_quote: "Example clause text",
    quote_score: 0.9,
    period_label: null,
    new_due_on: null,
    prompt_version: "example@0",
    model: "example-model",
    confidence: 0.75,
    issues: [{ code: "target_unaligned" }],
    needs_review: true,
    status: "rejected",
    reject_reason: "wrong_target",
    decided_by: analyst.userId,
    ...overrides,
  };
}

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("rulebookWriteClient", () => {
  it("refuses a session without a regulatory role before any request", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", WRITE_TOKEN);
    const fake = fakeFetch([]);
    for (const session of [owner, null]) {
      const result = rulebookWriteClient(ctx(session, fake));
      if (result.ok) throw new Error("expected a refusal");
      expect(result.error).toMatchObject({ kind: "forbidden", status: 403, requestId: "" });
      expect(problemSlug(result.error)).toBe("web-regulatory-role-required");
      expect(result.error.problem?.detail).toBe(t("rulebookWrites.roleRequiredDetail"));
    }
    expect(fake.requests).toHaveLength(0);
  });

  it("answers unavailable, naming the variable, while the write token is unset", () => {
    const result = rulebookWriteClient(ctx(analyst));
    if (result.ok) throw new Error("expected a refusal");
    expect(result.error).toMatchObject({
      kind: "unavailable",
      status: 503,
      message: t("rulebookWrites.writeTokenMissing"),
    });
    expect(problemSlug(result.error)).toBe("web-write-token-missing");
    expect(result.error.problem?.detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
  });

  it("sends the write token, and neither the review token nor a tenant header", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", WRITE_TOKEN);
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
    const fake = fakeFetch([{ path: "/v1/rulebook/rules", body: [] }]);
    const client = rulebookWriteClient({ ...ctx(admin, fake), tenantId: BUSINESS_TENANT });
    if (!client.ok) throw new Error("expected a client");
    await client.value.GET("/v1/rulebook/rules");
    const [request] = fake.requests;
    expect(request?.url).toBe(`${RULEBOOK}/v1/rulebook/rules`);
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBe(WRITE_TOKEN);
    expect(request?.headers[REVIEW_TOKEN_HEADER]).toBeUndefined();
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[REQUEST_ID_HEADER]).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe("rulebookReviewClient", () => {
  it("refuses a session without a regulatory role, even with the token configured", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
    const result = rulebookReviewClient(ctx(owner));
    if (result.ok) throw new Error("expected a refusal");
    expect(problemSlug(result.error)).toBe("web-regulatory-role-required");
  });

  it("answers unavailable, naming the variable, while the review token is unset", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", WRITE_TOKEN);
    const result = rulebookReviewClient(ctx(reviewer));
    if (result.ok) throw new Error("expected a refusal");
    expect(result.error).toMatchObject({
      kind: "unavailable",
      message: t("rulebookWrites.reviewTokenMissing"),
    });
    expect(problemSlug(result.error)).toBe("web-review-token-missing");
    expect(result.error.problem?.detail).toContain("CW_WEB_RULEBOOK_REVIEW_TOKEN");
    expectNoToken(result.error);
  });

  it("sends the review token, and neither the write token nor a tenant header", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", WRITE_TOKEN);
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
    const fake = fakeFetch([{ path: "/v1/rulebook/rules", body: [] }]);
    const client = rulebookReviewClient(ctx(analyst, fake));
    if (!client.ok) throw new Error("expected a client");
    await client.value.GET("/v1/rulebook/rules");
    const [request] = fake.requests;
    expect(request?.headers[REVIEW_TOKEN_HEADER]).toBe(REVIEW_TOKEN);
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
  });
});

describe("rulebookWriteAccess", () => {
  it("refuses a tenant role and a missing session first, whatever the flag and token say", async () => {
    allowDecisions();
    for (const session of [owner, null]) {
      const access = await rulebookWriteAccess(ctx(session));
      expect(access).toMatchObject({ allowed: false, refusal: "role", flag: RULEBOOK_WRITES_FLAG });
      if (access.allowed) throw new Error("expected a refusal");
      expect(problemSlug(access.error)).toBe("web-regulatory-role-required");
    }
  });

  it("refuses while the flag is off, naming the flag", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
    const access = await rulebookWriteAccess(ctx(analyst));
    expect(access).toMatchObject({
      allowed: false,
      refusal: "flag",
      flag: "web.admin_rulebook_writes",
    });
    if (access.allowed) throw new Error("expected a refusal");
    expect(access.error.kind).toBe("unavailable");
    expect(problemSlug(access.error)).toBe("web-rulebook-writes-off");
    expect(access.error.message).toBe("The web.admin_rulebook_writes flag is off");
    expect(access.error.problem?.detail).toContain("web.admin_rulebook_writes");
  });

  it("refuses without the review token; the write token does not open a decision", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", WRITE_TOKEN);
    const access = await rulebookWriteAccess(ctx(analyst));
    expect(access).toMatchObject({ allowed: false, refusal: "token" });
    if (access.allowed) throw new Error("expected a refusal");
    expect(problemSlug(access.error)).toBe("web-review-token-missing");
    expectNoToken(access.error);
  });

  it("allows every regulatory role with the flag on and the review token configured", async () => {
    allowDecisions();
    for (const session of [analyst, reviewer, admin]) {
      expect(await rulebookWriteAccess(ctx(session))).toEqual({ allowed: true });
    }
  });
});

describe("rulebookWrites", () => {
  it("answers every decision with the refusal, without a request, when it is refused", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", REVIEW_TOKEN);
    const fake = fakeFetch([]);
    const port = await rulebookWrites(ctx(analyst, fake));
    expect(port).toBeInstanceOf(RefusedWriteGateway);
    const results = [
      await port.decideEntityGroup({
        entityType: "form",
        proposedName: "Example form",
        decision: "create_entity",
        note: "",
      }),
      await port.approveCandidate(CANDIDATE_ID, { fromRuleVersionId: FROM_VERSION, note: "" }),
      await port.rejectCandidate(CANDIDATE_ID, { reason: "duplicate", note: "" }),
    ];
    for (const result of results) {
      if (result.ok) throw new Error("expected a refusal");
      expect(problemSlug(result.error)).toBe("web-rulebook-writes-off");
    }
    expect(fake.requests).toHaveLength(0);
  });

  it("refuses a tenant role before reading the flag or the token", async () => {
    allowDecisions();
    const fake = fakeFetch([]);
    const port = await rulebookWrites(ctx(owner, fake));
    const result = await port.rejectCandidate(CANDIDATE_ID, { reason: "duplicate", note: "" });
    if (result.ok) throw new Error("expected a refusal");
    expect(problemSlug(result.error)).toBe("web-regulatory-role-required");
    expect(fake.requests).toHaveLength(0);
  });

  it("decides an entity group with the review token and the session's user as decided_by", async () => {
    allowDecisions();
    const fake = fakeFetch([{ method: "POST", path: DECISIONS, body: decided }]);
    const port = await rulebookWrites(ctx(analyst, fake));
    expect(port).toBeInstanceOf(RulebookWriteGateway);
    const result = await port.decideEntityGroup({
      entityType: "form",
      proposedName: "Example form",
      decision: "add_alias",
      entityId: ENTITY_ID,
      reviewIds: REVIEW_IDS,
      note: "Example note",
    });
    expect(result).toMatchObject({
      ok: true,
      value: {
        status: "decided",
        resolution: "alias_added",
        entityId: ENTITY_ID,
        itemsClosed: 2,
        relationTargetsUpdated: 1,
      },
    });
    const [request] = fake.requests;
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe(`${RULEBOOK}${DECISIONS}`);
    expect(request?.headers[REVIEW_TOKEN_HEADER]).toBe(REVIEW_TOKEN);
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.body).toEqual({
      entity_type: "form",
      proposed_name: "Example form",
      decision: "add_alias",
      decided_by: analyst.userId,
      note: "Example note",
      entity_id: ENTITY_ID,
      review_ids: REVIEW_IDS,
    });
  });

  it("sends only the fields a decision carries, and never a decided_by from the caller", async () => {
    allowDecisions();
    const fake = fakeFetch([
      {
        method: "POST",
        path: DECISIONS,
        body: { ...decided, status: "rejected", resolution: null, entity_id: null },
      },
    ]);
    const port = await rulebookWrites(ctx(reviewer, fake));
    // A form cannot name someone else: an extra decided_by is not part of the body.
    const decision = {
      entityType: "form",
      proposedName: "Example form",
      decision: "reject",
      rejectReason: "not_an_entity",
      note: "",
      decided_by: "someone-else",
    } as EntityGroupDecision;
    const result = await port.decideEntityGroup(decision);
    expect(result).toMatchObject({ ok: true, value: { resolution: null, entityId: null } });
    expect(fake.requests[0]?.body).toEqual({
      entity_type: "form",
      proposed_name: "Example form",
      decision: "reject",
      decided_by: reviewer.userId,
      note: "",
      reject_reason: "not_an_entity",
    });
  });

  it("approves a candidate into a rule relation, with the target version when it has one", async () => {
    allowDecisions();
    const approved: ApprovalOutDto = { candidate_id: CANDIDATE_ID, rule_relation_id: RELATION_ID };
    const fake = fakeFetch([{ method: "POST", path: APPROVE, body: approved }]);
    const port = await rulebookWrites(ctx(admin, fake));
    const withTarget = await port.approveCandidate(CANDIDATE_ID, {
      fromRuleVersionId: FROM_VERSION,
      targetRuleVersionId: TARGET_VERSION,
      note: "Example note",
    });
    expect(withTarget).toMatchObject({
      ok: true,
      value: { candidateId: CANDIDATE_ID, ruleRelationId: RELATION_ID },
    });
    await port.approveCandidate(CANDIDATE_ID, { fromRuleVersionId: FROM_VERSION, note: "" });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${RULEBOOK}${APPROVE}`,
      `${RULEBOOK}${APPROVE}`,
    ]);
    expect(fake.requests[0]?.headers[REVIEW_TOKEN_HEADER]).toBe(REVIEW_TOKEN);
    expect(fake.requests[0]?.body).toEqual({
      from_rule_version_id: FROM_VERSION,
      target_rule_version_id: TARGET_VERSION,
      decided_by: admin.userId,
      note: "Example note",
    });
    expect(fake.requests[1]?.body).toEqual({
      from_rule_version_id: FROM_VERSION,
      decided_by: admin.userId,
      note: "",
    });
  });

  it("rejects a candidate and maps the candidate the rulebook answers", async () => {
    allowDecisions();
    const fake = fakeFetch([{ method: "POST", path: REJECT, body: candidateDto() }]);
    const port = await rulebookWrites(ctx(analyst, fake));
    const result = await port.rejectCandidate(CANDIDATE_ID, {
      reason: "wrong_target",
      note: "Example note",
    });
    expect(fake.requests[0]?.body).toEqual({
      reason: "wrong_target",
      decided_by: analyst.userId,
      note: "Example note",
    });
    if (!result.ok) throw new Error("expected the candidate");
    expect(result.value).toEqual({
      candidateId: CANDIDATE_ID,
      documentId: DOCUMENT_ID,
      relation: "refers_to",
      targetType: "form",
      targetName: "Example form",
      targetEntityId: null,
      targetRuleKey: null,
      evidenceClauseId: CLAUSE_ID,
      evidenceQuote: "Example clause text",
      quoteScore: 0.9,
      periodLabel: null,
      newDueOn: null,
      promptVersion: "example@0",
      model: "example-model",
      confidence: 0.75,
      issues: [{ code: "target_unaligned", detail: "" }],
      needsReview: true,
      status: "rejected",
      rejectReason: "wrong_target",
      decidedBy: analyst.userId,
    });
  });

  it("rewords the rulebook's token refusals to say which side to fix, without the token", async () => {
    allowDecisions();
    const fake = fakeFetch([
      {
        method: "POST",
        path: APPROVE,
        status: 401,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}rulebook-review-token-invalid`,
          title: "Review token missing or wrong",
        },
      },
      {
        method: "POST",
        path: REJECT,
        status: 503,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}rulebook-reviews-disabled`,
          title: "Rulebook analyst actions are not configured",
        },
      },
    ]);
    const port = await rulebookWrites(ctx(analyst, fake));

    const wrong = await port.approveCandidate(CANDIDATE_ID, {
      fromRuleVersionId: FROM_VERSION,
      note: "",
    });
    if (wrong.ok) throw new Error("expected a refusal");
    expect(wrong.error).toMatchObject({
      kind: "unauthenticated",
      status: 401,
      message: t("rulebookWrites.reviewTokenInvalid"),
      requestId: fake.requests[0]?.headers[REQUEST_ID_HEADER],
    });
    expect(wrong.error.problem?.title).toBe(t("rulebookWrites.reviewTokenInvalid"));
    expect(wrong.error.problem?.detail).toContain("CW_WEB_RULEBOOK_REVIEW_TOKEN");
    expectNoToken(wrong.error);

    const unset = await port.rejectCandidate(CANDIDATE_ID, { reason: "duplicate", note: "" });
    if (unset.ok) throw new Error("expected a refusal");
    expect(unset.error).toMatchObject({
      kind: "unavailable",
      message: t("rulebookWrites.reviewsDisabled"),
    });
    expect(unset.error.problem?.detail).toContain("CW_RULEBOOK_REVIEW_TOKEN");
    expectNoToken(unset.error);
  });

  it("passes any other problem through unchanged, with its field errors", async () => {
    allowDecisions();
    const fake = fakeFetch([
      {
        method: "POST",
        path: DECISIONS,
        status: 409,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}rulebook-review-group-closed`,
          title: "Example group is closed",
        },
      },
      {
        method: "POST",
        path: APPROVE,
        status: 422,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}rulebook-target-version-required`,
          title: "Example target version required",
          errors: [
            {
              loc: ["body", "target_rule_version_id"],
              msg: "Example message",
              type: "value_error",
            },
          ],
        },
      },
    ]);
    const port = await rulebookWrites(ctx(analyst, fake));
    const closed = await port.decideEntityGroup({
      entityType: "form",
      proposedName: "Example form",
      decision: "create_entity",
      note: "",
    });
    expect(closed).toMatchObject({
      ok: false,
      error: { kind: "conflict", message: "Example group is closed" },
    });
    const invalid = await port.approveCandidate(CANDIDATE_ID, {
      fromRuleVersionId: FROM_VERSION,
      note: "",
    });
    expect(invalid).toMatchObject({
      ok: false,
      error: {
        kind: "validation",
        message: "Example target version required",
        fieldErrors: { target_rule_version_id: ["Example message"] },
      },
    });
  });
});

describe("explainTokenProblem", () => {
  function refusal(slug: string, status: number): ApiError {
    return {
      kind: status === 401 ? "unauthenticated" : "unavailable",
      status,
      requestId: "00000000-0000-4000-8000-0000000000aa",
      message: "Example title from the rulebook",
      problem: { type: `${PROBLEM_TYPE_PREFIX}${slug}`, title: "Example title", status },
    };
  }

  it("names the web app's variable for a wrong write token", () => {
    const error = explainTokenProblem(refusal("rulebook-write-token-invalid", 401));
    expect(error).toMatchObject({
      kind: "unauthenticated",
      status: 401,
      requestId: "00000000-0000-4000-8000-0000000000aa",
      message: t("rulebookWrites.writeTokenInvalid"),
      problem: {
        title: t("rulebookWrites.writeTokenInvalid"),
        detail: t("rulebookWrites.writeTokenInvalidDetail"),
      },
    });
    expect(error.problem?.detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
  });

  it("names the rulebook's variable when the rulebook has no write token", () => {
    const error = explainTokenProblem(refusal("rulebook-writes-disabled", 503));
    expect(error.message).toBe(t("rulebookWrites.writesDisabled"));
    expect(error.problem?.detail).toContain("CW_RULEBOOK_WRITE_TOKEN");
    expect(error.problem?.type).toBe(`${PROBLEM_TYPE_PREFIX}rulebook-writes-disabled`);
  });

  it("returns any other error as it was", () => {
    const other = refusal("rulebook-entity-not-found", 404);
    expect(explainTokenProblem(other)).toBe(other);
    const local = webError("unavailable", "web-review-token-missing", "Example title");
    expect(explainTokenProblem(local)).toBe(local);
    const network: ApiError = { kind: "network", requestId: "", message: "Example message" };
    expect(explainTokenProblem(network)).toBe(network);
  });
});

// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { relationCandidateFromDto } from "@/entities/rulebook/mappers";
import type { CandidateStatus, ClauseDetail, RelationCandidate } from "@/entities/rulebook/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { err, ok, webError, type Result } from "@/server/result";
import { fakeFetch } from "@/test/fake-fetch";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { ruleDto, ruleVersionDto } from "@/test/rule-version-fixture";
import type { RelationReviewPort } from "./ports";
import { findCandidate, getCandidatePage, getCandidateQueue } from "./queries";

const analyst: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b1",
  tenantId: "00000000-0000-4000-8000-000000000001",
  tenantKind: "internal",
  roles: ["analyst"],
};

/** A port holding candidates in the statuses given, answering the list's keyset like the rulebook. */
class FakePort implements RelationReviewPort {
  readonly asked: CandidateStatus[] = [];
  constructor(
    private readonly stored: readonly RelationCandidate[],
    private readonly failing: CandidateStatus | null = null,
  ) {}

  async candidates(query: {
    status: CandidateStatus;
    after: string | null;
    limit: number;
  }): Promise<Result<RelationCandidate[]>> {
    this.asked.push(query.status);
    if (query.status === this.failing) return err(webError("server", "web-example", "Example"));
    return ok(
      this.stored
        .filter((candidate) => candidate.status === query.status)
        .filter((candidate) => query.after === null || candidate.candidateId > query.after)
        .sort((a, b) => a.candidateId.localeCompare(b.candidateId))
        .slice(0, query.limit),
    );
  }

  async clause(): Promise<Result<ClauseDetail>> {
    return err(webError("not_found", "web-example", "Example"));
  }

  async rules(): Promise<Result<RuleSummary[]>> {
    return ok([]);
  }

  async versionsOf(): Promise<Result<RuleVersion[]>> {
    return ok([]);
  }
}

function candidate(id: string, status: CandidateStatus): RelationCandidate {
  return relationCandidateFromDto(relationCandidateDto({ candidate_id: id, status }));
}

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("findCandidate", () => {
  const stored = [
    candidate("00000000-0000-4000-8000-0000000000c9", "open"),
    candidate(EXAMPLE_CANDIDATE_ID, "rejected"),
    candidate("00000000-0000-4000-8000-0000000000cb", "rejected"),
  ];

  it("finds a candidate one row after the id before it, in the address's status first", async () => {
    const port = new FakePort(stored);
    const found = await findCandidate(port, EXAMPLE_CANDIDATE_ID, "rejected");
    expect(found.ok && found.value?.candidateId).toBe(EXAMPLE_CANDIDATE_ID);
    expect(port.asked).toEqual(["rejected"]);
  });

  it("looks through every status and answers null when none holds it", async () => {
    const port = new FakePort(stored);
    const found = await findCandidate(port, EXAMPLE_CANDIDATE_ID);
    expect(found.ok && found.value?.status).toBe("rejected");
    expect(port.asked).toEqual(["open", "approved", "rejected"]);
    const missing = await findCandidate(
      new FakePort(stored),
      "00000000-0000-4000-8000-0000000000ff",
    );
    expect(missing).toEqual({ ok: true, value: null });
  });

  it("passes a failed read on", async () => {
    const found = await findCandidate(new FakePort(stored, "open"), EXAMPLE_CANDIDATE_ID);
    expect(found.ok).toBe(false);
  });
});

describe("getCandidateQueue", () => {
  it("asks for one candidate more than a page", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/review/relations", body: [] }]);
    const queue = await getCandidateQueue(
      { status: "open", documentId: null, after: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(fake.requests[0]?.url).toContain("limit=26");
    expect(queue.ok && queue.value.rows).toEqual([]);
  });
});

describe("getCandidatePage", () => {
  const clause = {
    clause_id: EXAMPLE_CLAUSE_IDS.first,
    document_id: EXAMPLE_DOCUMENT_ID,
    clause_ref: "en.p1",
    ordinal: 1,
    page: 1,
    text: "Example clause text that opens the document.",
    regulator: "Example regulator",
    doc_type: "circular",
    external_ref: "Example 1/2000",
    title: "Example document title",
    url: "https://example.com/example.pdf",
    language: "en",
    published_at: null,
  };

  it("puts an open candidate with its evidence and the versions it may take together", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
      { path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`, body: clause },
      { path: "/v1/rulebook/rules", body: [ruleDto(), ruleDto({ rule_key: "example_gone" })] },
      { path: "/v1/rulebook/rules/example_rule/versions", body: [ruleVersionDto()] },
      { path: "/v1/rulebook/rules/example_gone/versions", status: 404, problem: { title: "Gone" } },
    ]);
    const page = await getCandidatePage(analyst, EXAMPLE_CANDIDATE_ID, "open", {
      fetchImpl: fake.fetchImpl,
    });
    expect(page.ok).toBe(true);
    const value = page.ok ? page.value : null;
    expect(value?.facts.candidateId).toBe(EXAMPLE_CANDIDATE_ID);
    expect(value?.evidence.mark?.mark).toBe("clause text that opens");
    expect(value?.access).toEqual({ allowed: true });
    expect(value?.needsTarget).toBe(true);
    expect(value?.options?.from.map((option) => option.value)).toEqual([
      ruleVersionFromDto(ruleVersionDto()).ruleVersionId,
    ]);
    expect(value?.optionsError).toBeNull();
    expect(fake.requests[0]?.url).toContain("after=00000000-0000-4000-8000-0000000000c9");
    expect(fake.requests[0]?.url).toContain("limit=1");
  });

  it("offers no versions while the flag holds decisions back, and keeps a failed clause read", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
      {
        path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`,
        status: 503,
        problem: { title: "Example outage" },
      },
    ]);
    const page = await getCandidatePage(analyst, EXAMPLE_CANDIDATE_ID, undefined, {
      fetchImpl: fake.fetchImpl,
    });
    const value = page.ok ? page.value : null;
    expect(value?.access).toMatchObject({ allowed: false });
    expect(value?.options).toBeNull();
    expect(value?.evidence.mark).toBeNull();
    expect(value?.evidenceError?.message).toBe("Example outage");
    expect(fake.requests.map((request) => new URL(request.url).pathname)).not.toContain(
      "/v1/rulebook/rules",
    );
  });

  it("answers null for an id no status holds", async () => {
    const empty = fakeFetch([{ path: "/v1/rulebook/review/relations", body: [] }]);
    expect(
      await getCandidatePage(analyst, EXAMPLE_CANDIDATE_ID, "open", { fetchImpl: empty.fetchImpl }),
    ).toEqual({ ok: true, value: null });
    expect(empty.requests).toHaveLength(3);
  });

  it("says when the versions an approval may take cannot be read", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
      { path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`, body: clause },
      { path: "/v1/rulebook/rules", body: [ruleDto()] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        status: 503,
        problem: { title: "Example versions outage" },
      },
    ]);
    const page = await getCandidatePage(analyst, EXAMPLE_CANDIDATE_ID, "open", {
      fetchImpl: fake.fetchImpl,
    });
    const value = page.ok ? page.value : null;
    expect(value?.options).toBeNull();
    expect(value?.optionsError?.message).toBe("Example versions outage");
  });

  it("reads no versions for a decided candidate", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([
      {
        path: "/v1/rulebook/review/relations",
        body: [relationCandidateDto({ status: "approved", decided_by: "example-user" })],
      },
      { path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`, body: clause },
    ]);
    const page = await getCandidatePage(analyst, EXAMPLE_CANDIDATE_ID, "approved", {
      fetchImpl: fake.fetchImpl,
    });
    const value = page.ok ? page.value : null;
    expect(value?.facts.open).toBe(false);
    expect(value?.options).toBeNull();
    expect(fake.requests).toHaveLength(2);
  });
});

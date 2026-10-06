// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { ruleDto, ruleVersionDto } from "@/test/rule-version-fixture";
import { relationReviewGateway } from "./gateway";

afterEach(() => {
  resetEnvCache();
});

const CLAUSE = {
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

describe("RelationReviewGateway", () => {
  it("reads candidates of a status, a document and after an id, fresh and without a tenant", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
    ]);
    const page = await relationReviewGateway({ fetchImpl: fake.fetchImpl }).candidates({
      status: "approved",
      documentId: EXAMPLE_DOCUMENT_ID,
      after: EXAMPLE_CANDIDATE_ID,
      limit: 26,
    });
    expect(page.ok && page.value[0]?.candidateId).toBe(EXAMPLE_CANDIDATE_ID);
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8003/v1/rulebook/review/relations?status=approved&limit=26&document_id=${EXAMPLE_DOCUMENT_ID}&after=${EXAMPLE_CANDIDATE_ID}`,
    );
    expect(fake.requests[0]?.cache).toBe("no-store");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("caches the evidence clause and the rule list under their tags, and reads versions fresh", async () => {
    const fake = fakeFetch([
      { path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`, body: CLAUSE },
      { path: "/v1/rulebook/rules", body: [ruleDto()] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        body: [ruleVersionDto({ closed: true })],
      },
    ]);
    const gateway = relationReviewGateway({ fetchImpl: fake.fetchImpl });
    const clause = await gateway.clause(EXAMPLE_CLAUSE_IDS.first);
    const rules = await gateway.rules();
    const versions = await gateway.versionsOf("example_rule");
    expect(clause.ok && clause.value.clauseRef).toBe("en.p1");
    expect(rules.ok && rules.value[0]?.ruleKey).toBe("example_rule");
    expect(versions.ok && versions.value[0]?.closed).toBe(true);
    expect(fake.requests[0]?.next?.tags).toEqual([`rulebook:clause:${EXAMPLE_CLAUSE_IDS.first}`]);
    expect(fake.requests[1]?.next?.tags).toEqual(["rulebook:rules"]);
    expect(fake.requests[2]?.cache).toBe("no-store");
  });
});

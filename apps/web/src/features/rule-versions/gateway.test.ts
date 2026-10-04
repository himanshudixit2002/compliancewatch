// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER, WRITE_TOKEN_HEADER } from "@/server/api/client";
import { REVIEW_TOKEN_HEADER } from "@/server/api/rulebook-write";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import {
  EXAMPLE_VERSION_ID,
  citationDto,
  ruleDto,
  ruleVersionDetailDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import { RELATIONS_LIMIT, ruleVersionsGateway } from "./gateway";

const RULEBOOK = "http://localhost:8003";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("RuleVersionsGateway", () => {
  it("reads rules, versions and citations fresh, with no tenant header and no token", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([
      { path: "/v1/rulebook/rules", body: [ruleDto()] },
      { path: "/v1/rulebook/rules/example_rule/versions", body: [ruleVersionDto()] },
      { path: `/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`, body: ruleVersionDetailDto() },
      { path: `/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}/citations`, body: [citationDto()] },
    ]);
    const gateway = ruleVersionsGateway({ fetchImpl: fake.fetchImpl });
    expect(await gateway.rules()).toMatchObject({ ok: true, value: [{ ruleKey: "example_rule" }] });
    expect(await gateway.versionsOf("example_rule")).toMatchObject({
      ok: true,
      value: [{ status: "draft" }],
    });
    expect(await gateway.version(EXAMPLE_VERSION_ID)).toMatchObject({
      ok: true,
      value: { ruleVersionId: EXAMPLE_VERSION_ID },
    });
    expect(await gateway.citations(EXAMPLE_VERSION_ID)).toMatchObject({
      ok: true,
      value: [{ clauseRef: "en.p1" }],
    });
    for (const request of fake.requests) {
      expect(request.method).toBe("GET");
      expect(request.cache).toBe("no-store");
      expect(request.headers[TENANT_HEADER]).toBeUndefined();
      expect(request.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
      expect(request.headers[REVIEW_TOKEN_HEADER]).toBeUndefined();
    }
  });

  it("asks for the versions in force on a date, a page after a rule key", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/rule-versions", body: [] }]);
    const gateway = ruleVersionsGateway({ fetchImpl: fake.fetchImpl });
    await gateway.inForce({ asOf: "2000-06-30", limit: 26 });
    await gateway.inForce({
      asOf: "2000-06-30",
      limit: 26,
      ruleKey: "example_rule",
      after: "example_a",
    });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${RULEBOOK}/v1/rulebook/rule-versions?as_of=2000-06-30&limit=26`,
      `${RULEBOOK}/v1/rulebook/rule-versions?as_of=2000-06-30&limit=26&rule_key=example_rule&after=example_a`,
    ]);
  });

  it("reads a clause under its own cache tag", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/rulebook/clauses/${EXAMPLE_CLAUSE_IDS.first}`,
        body: {
          clause_id: EXAMPLE_CLAUSE_IDS.first,
          document_id: EXAMPLE_DOCUMENT_ID,
          clause_ref: "en.p1",
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
        },
      },
    ]);
    const clause = await ruleVersionsGateway({ fetchImpl: fake.fetchImpl }).clause(
      EXAMPLE_CLAUSE_IDS.first,
    );
    expect(clause).toMatchObject({ ok: true, value: { externalRef: "Example 1/2000" } });
    expect(fake.requests[0]?.next).toEqual({
      revalidate: 300,
      tags: [`rulebook:clause:${EXAMPLE_CLAUSE_IDS.first}`],
    });
  });

  it("reads the relations from and to a version, drafts' relations included", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/relations", body: [] }]);
    const gateway = ruleVersionsGateway({ fetchImpl: fake.fetchImpl });
    await gateway.relations({ from: EXAMPLE_VERSION_ID });
    await gateway.relations({ to: EXAMPLE_VERSION_ID });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${RULEBOOK}/v1/rulebook/relations?published_only=false&limit=${RELATIONS_LIMIT}&from_rule_version_id=${EXAMPLE_VERSION_ID}`,
      `${RULEBOOK}/v1/rulebook/relations?published_only=false&limit=${RELATIONS_LIMIT}&to_rule_version_id=${EXAMPLE_VERSION_ID}`,
    ]);
  });

  it("passes the rulebook's not-found problem on", async () => {
    const fake = fakeFetch([
      {
        path: /\/v1\/rulebook\/rule-versions\//,
        status: 404,
        problem: { type: "urn:compliancewatch:problem:rulebook-rule-version-not-found" },
      },
    ]);
    const version = await ruleVersionsGateway({ fetchImpl: fake.fetchImpl }).version(
      EXAMPLE_VERSION_ID,
    );
    expect(version).toMatchObject({ ok: false, error: { kind: "not_found" } });
  });
});

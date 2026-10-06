// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { REVIEWED_TENANT_ID, RUN_VERSION_ID, dryRunOutDto } from "@/test/engine-admin-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { impactExplorerGateway } from "./gateway";

afterEach(() => {
  resetEnvCache();
});

describe("ImpactExplorerGateway", () => {
  it("posts the dry run with its scope and no tenant header, and maps the report", async () => {
    const fake = fakeFetch([
      { method: "POST", path: "/v1/applicability-engine/dry-runs", body: dryRunOutDto() },
    ]);
    const report = await impactExplorerGateway({ fetchImpl: fake.fetchImpl }).dryRun({
      ruleVersionId: RUN_VERSION_ID,
      specification: null,
      level: null,
      tenantId: REVIEWED_TENANT_ID,
      sampleSize: 5,
    });
    expect(report.ok && report.value.counts).toEqual({ applies: 1, notApplicable: 1, unsure: 1 });
    expect(fake.requests[0]?.url).toBe("http://localhost:8004/v1/applicability-engine/dry-runs");
    expect(fake.requests[0]?.body).toEqual({
      rule_version_id: RUN_VERSION_ID,
      scope: { sample_size: 5, tenant_id: REVIEWED_TENANT_ID },
    });
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("passes the engine's refusal of a scope too large", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/applicability-engine/dry-runs",
        status: 422,
        problem: { type: "urn:compliancewatch:problem:applicability-dry-run-too-large" },
      },
    ]);
    const report = await impactExplorerGateway({ fetchImpl: fake.fetchImpl }).dryRun({
      ruleVersionId: RUN_VERSION_ID,
      specification: null,
      level: null,
      tenantId: null,
      sampleSize: 10,
    });
    expect(!report.ok && report.error.kind).toBe("validation");
  });
});

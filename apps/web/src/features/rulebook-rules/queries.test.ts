// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { ruleDto } from "@/test/rule-version-fixture";
import { getRules } from "./queries";

afterEach(() => {
  resetEnvCache();
});

describe("getRules", () => {
  it("reads the rules once per five minutes under their tag, without a tenant", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/rules", body: [ruleDto()] }]);
    const rows = await getRules({ fetchImpl: fake.fetchImpl });
    expect(rows.ok && rows.value.map((row) => row.ruleKey)).toEqual(["example_rule"]);
    expect(fake.requests[0]?.url).toBe("http://localhost:8003/v1/rulebook/rules");
    expect(fake.requests[0]?.next).toEqual({ revalidate: 300, tags: ["rulebook:rules"] });
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("passes a failed read on", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/rules", status: 503, problem: { title: "Example outage" } },
    ]);
    const rows = await getRules({ fetchImpl: fake.fetchImpl });
    expect(!rows.ok && rows.error.message).toBe("Example outage");
  });
});

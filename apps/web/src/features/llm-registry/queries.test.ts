// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { LLM_FEATURES } from "@/entities/llm/types";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { EXAMPLE_TENANT_ID, modelRouteDto, promptDto, usageDto } from "@/test/llm-fixture";
import { getModels, getPrompts, getUsage } from "./queries";

afterEach(() => {
  resetEnvCache();
});

describe("getUsage", () => {
  it("reads every feature's budget for the month, one read each", async () => {
    const fake = fakeFetch((request) =>
      Response.json(
        usageDto({ key: new URL(request.url).searchParams.get("feature") ?? "", month: "2000-01" }),
      ),
    );
    const usage = await getUsage(
      { kind: "overview", month: "2000-01" },
      { fetchImpl: fake.fetchImpl },
    );
    expect(fake.requests).toHaveLength(LLM_FEATURES.length);
    expect(usage.ok && usage.value).toMatchObject({
      month: "2000-01",
      monthLabel: "January 2000",
      overview: true,
    });
    expect(usage.ok && usage.value.rows.map((row) => row.key)).toEqual(
      LLM_FEATURES.map((feature) => `feature:${feature}`),
    );
  });

  it("reads one tenant's budget, and fails as a whole when the gateway fails", async () => {
    const one = fakeFetch([
      {
        path: "/v1/llm-gateway/usage",
        body: usageDto({ scope: "tenant", key: EXAMPLE_TENANT_ID }),
      },
    ]);
    const usage = await getUsage(
      { kind: "one", month: "2000-01", tenantId: EXAMPLE_TENANT_ID },
      { fetchImpl: one.fetchImpl },
    );
    expect(usage.ok && usage.value.rows).toHaveLength(1);
    expect(usage.ok && usage.value.overview).toBe(false);
    expect(usage.ok && usage.value.rows[0]?.scopeLabel).toBe("Tenant");
    const narrowed = await getUsage(
      { kind: "one", month: "2000-01", tenantId: EXAMPLE_TENANT_ID, feature: "qa" },
      { fetchImpl: one.fetchImpl },
    );
    expect(new URL(one.requests[1]?.url ?? "").searchParams.get("feature")).toBe("qa");
    expect(narrowed.ok && narrowed.value.rows[0]?.scopeLabel).toBe("Tenant budget, QA spend only");
    const failing = fakeFetch([
      { path: "/v1/llm-gateway/usage", status: 422, problem: { title: "Example refusal" } },
    ]);
    const refused = await getUsage(
      { kind: "overview", month: "2000-01" },
      { fetchImpl: failing.fetchImpl },
    );
    expect(!refused.ok && refused.error.message).toBe("Example refusal");
  });
});

describe("the registries", () => {
  it("map the prompts and the routes into rows", async () => {
    const fake = fakeFetch([
      { path: "/v1/llm-gateway/prompts", body: [promptDto()] },
      { path: "/v1/llm-gateway/models", body: [modelRouteDto()] },
    ]);
    const prompts = await getPrompts({ fetchImpl: fake.fetchImpl });
    const models = await getModels({ fetchImpl: fake.fetchImpl });
    expect(prompts.ok && prompts.value[0]?.key).toBe("example.prompt@1");
    expect(models.ok && models.value[0]?.featureLabel).toBe("QA");
  });
});

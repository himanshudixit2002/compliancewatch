// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { EXAMPLE_TENANT_ID, modelRouteDto, promptDto, usageDto } from "@/test/llm-fixture";
import { llmRegistryGateway } from "./gateway";

afterEach(() => {
  resetEnvCache();
});

describe("LlmRegistryGateway", () => {
  it("reads the prompts and the routes under their tags, without a tenant header", async () => {
    const fake = fakeFetch([
      { path: "/v1/llm-gateway/prompts", body: [promptDto()] },
      { path: "/v1/llm-gateway/models", body: [modelRouteDto()] },
    ]);
    const gateway = llmRegistryGateway({ fetchImpl: fake.fetchImpl });
    const prompts = await gateway.prompts();
    const models = await gateway.models();
    expect(prompts.ok && prompts.value[0]?.name).toBe("example.prompt");
    expect(models.ok && models.value[0]?.feature).toBe("qa");
    expect(fake.requests.map((request) => request.url)).toEqual([
      "http://localhost:8008/v1/llm-gateway/prompts",
      "http://localhost:8008/v1/llm-gateway/models",
    ]);
    expect(fake.requests[0]?.next?.tags).toEqual(["llm-gateway:prompts"]);
    expect(fake.requests[1]?.next?.tags).toEqual(["llm-gateway:models"]);
    for (const request of fake.requests) expect(request.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("reads spend fresh, naming the tenant in the query and never in the header", async () => {
    const fake = fakeFetch([{ path: "/v1/llm-gateway/usage", body: usageDto() }]);
    const gateway = llmRegistryGateway({ fetchImpl: fake.fetchImpl });
    await gateway.usage({ tenantId: EXAMPLE_TENANT_ID, feature: "qa", month: "2000-01" });
    await gateway.usage({ feature: "smoke", month: "2000-02" });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `http://localhost:8008/v1/llm-gateway/usage?month=2000-01&tenant_id=${EXAMPLE_TENANT_ID}&feature=qa`,
      "http://localhost:8008/v1/llm-gateway/usage?month=2000-02&feature=smoke",
    ]);
    expect(fake.requests[0]?.cache).toBe("no-store");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
  });
});

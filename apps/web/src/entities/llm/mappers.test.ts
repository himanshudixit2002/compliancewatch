import { describe, expect, it } from "vitest";
import { modelRouteDto, promptDto, usageDto } from "@/test/llm-fixture";
import { modelRouteFromDto, promptFromDto, usageFromDto } from "./mappers";

describe("the LLM gateway mappers", () => {
  it("map a prompt, keeping a missing hash as null", () => {
    expect(promptFromDto(promptDto())).toMatchObject({ name: "example.prompt", evalCases: 3 });
    expect(promptFromDto(promptDto({ sha256: null })).sha256).toBeNull();
  });

  it("map a model route with its lists and an absent fallback", () => {
    expect(modelRouteFromDto(modelRouteDto({ fallback: null, sort: "price" }))).toEqual({
      feature: "qa",
      primary: "example/model-a",
      fallback: null,
      only: ["example-provider"],
      has: [],
      sort: "price",
      reasoningEffort: "low",
      timeoutSeconds: 30,
      source: "default",
    });
  });

  it("keep money and the ratio as the decimal text the gateway sent", () => {
    expect(usageFromDto(usageDto())).toEqual({
      scope: "feature",
      key: "qa",
      month: "2000-01",
      spentInr: "1234.0012",
      budgetInr: "20000",
      ratio: "0.061700",
      alarmed: false,
      resetsAt: "2000-02-01T00:00:00Z",
    });
  });
});

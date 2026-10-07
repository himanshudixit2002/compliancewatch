import type { ModelRouteDto, PromptDto, UsageDto } from "@/entities/llm/types";

/**
 * The LLM gateway's registries and spend for unit tests: obviously synthetic ("example" prompts
 * and models, the year 2000), never a provider's real model.
 */
export const EXAMPLE_TENANT_ID = "00000000-0000-4000-8000-0000000000aa";

export function promptDto(overrides: Partial<PromptDto> = {}): PromptDto {
  return {
    name: "example.prompt",
    version: "1",
    owner: "example-team",
    eval_cases: 3,
    sha256: "0123456789abcdef".repeat(4),
    description: "Example prompt that answers an example question.",
    ...overrides,
  };
}

export function modelRouteDto(overrides: Partial<ModelRouteDto> = {}): ModelRouteDto {
  return {
    feature: "qa",
    primary: "example/model-a",
    fallback: "example/model-b",
    only: ["example-provider"],
    has: [],
    sort: null,
    reasoning_effort: "low",
    timeout_seconds: 30,
    source: "default",
    residency: { policy: "global", real_models_allowed: true },
    ...overrides,
  };
}

export function usageDto(overrides: Partial<UsageDto> = {}): UsageDto {
  return {
    scope: "feature",
    key: "qa",
    month: "2000-01",
    spent_inr: "1234.0012",
    budget_inr: "20000",
    ratio: "0.061700",
    alarmed: false,
    resets_at: "2000-02-01T00:00:00Z",
    ...overrides,
  };
}

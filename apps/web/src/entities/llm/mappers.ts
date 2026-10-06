import type { ModelRoute, ModelRouteDto, Prompt, PromptDto, Usage, UsageDto } from "./types";

export function promptFromDto(dto: PromptDto): Prompt {
  return {
    name: dto.name,
    version: dto.version,
    owner: dto.owner,
    evalCases: dto.eval_cases,
    sha256: dto.sha256 ?? null,
    description: dto.description,
  };
}

export function modelRouteFromDto(dto: ModelRouteDto): ModelRoute {
  return {
    feature: dto.feature,
    primary: dto.primary,
    fallback: dto.fallback ?? null,
    only: [...dto.only],
    has: [...dto.has],
    sort: dto.sort ?? null,
    reasoningEffort: dto.reasoning_effort ?? null,
    timeoutSeconds: dto.timeout_seconds,
    source: dto.source,
  };
}

export function usageFromDto(dto: UsageDto): Usage {
  return {
    scope: dto.scope,
    key: dto.key,
    month: dto.month,
    spentInr: dto.spent_inr,
    budgetInr: dto.budget_inr,
    ratio: dto.ratio,
    alarmed: dto.alarmed,
    resetsAt: dto.resets_at,
  };
}

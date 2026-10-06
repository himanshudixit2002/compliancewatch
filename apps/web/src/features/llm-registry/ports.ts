import type { LlmFeature, ModelRoute, Prompt, Usage } from "@/entities/llm/types";
import type { Result } from "@/server/result";

/** What the LLM gateway pages read; none of them writes. */
export interface LlmRegistryPort {
  /** The prompts the gateway serves, by name and version. */
  prompts(): Promise<Result<Prompt[]>>;
  /** Each feature's model route with any override applied. */
  models(): Promise<Result<ModelRoute[]>>;
  /**
   * Spend against one monthly budget: a tenant's (a feature narrows the sum) or a feature's.
   * `month` is YYYY-MM in UTC.
   */
  usage(query: { tenantId?: string; feature?: LlmFeature; month: string }): Promise<Result<Usage>>;
}

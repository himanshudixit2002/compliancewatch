import type { llmGateway } from "@compliancewatch/contracts/openapi";
import { membersOf } from "@/shared/lib/union";

/**
 * The LLM gateway's registries and spend as the gateway reports them: the prompts it serves, the
 * model route of each feature with any override applied, and the spend against one monthly
 * budget. Money is decimal text in rupees with as many places as the ledger holds ("0.0012"),
 * never a float; a ratio is decimal text with six places.
 */
type Schemas = llmGateway.components["schemas"];

export type PromptDto = Schemas["PromptOut"];
export type ModelRouteDto = Schemas["ModelRouteOut"];
export type UsageDto = Schemas["UsageOut"];
export type LlmFeature = Schemas["Feature"];
export type BudgetScope = Schemas["BudgetScope"];

/**
 * What a call is for (the gateway's Feature): routes, budgets and the ledger are keyed by it. Every
 * feature of the spec, in its order, checked against the union (a feature the gateway adds breaks
 * the build here instead of missing from the usage overview).
 */
export const LLM_FEATURES = membersOf<LlmFeature>({
  extraction: true,
  judgement: true,
  qa: true,
  classification: true,
  smoke: true,
  retrieval: true,
});

export interface Prompt {
  name: string;
  version: string;
  owner: string;
  /** Golden cases the prompt is evaluated on; none means no eval guards it. */
  evalCases: number;
  /** The hash of the prompt's text, when the registry recorded one. */
  sha256: string | null;
  description: string;
}

export interface ModelRoute {
  feature: LlmFeature;
  primary: string;
  fallback: string | null;
  only: readonly string[];
  has: readonly string[];
  sort: string | null;
  reasoningEffort: string | null;
  timeoutSeconds: number;
  /** "override" when the gateway's environment replaced the default route. */
  source: "default" | "override";
}

export interface Usage {
  scope: BudgetScope;
  /** The tenant id or the feature the budget belongs to. */
  key: string;
  /** YYYY-MM, in UTC. */
  month: string;
  spentInr: string;
  budgetInr: string;
  /** spent over budget, decimal text. */
  ratio: string;
  alarmed: boolean;
  /** When the month's budget starts again, an instant. */
  resetsAt: string;
}

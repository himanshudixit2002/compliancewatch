import type { RuleSummary } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** The rule list's one read. */
export interface RulesPort {
  /** Every rule by key, each with the title of its latest version. */
  rules(): Promise<Result<RuleSummary[]>>;
}

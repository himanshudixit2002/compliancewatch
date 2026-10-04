import type { ClauseDetail, RuleRelation } from "@/entities/rulebook/types";
import type { Citation, RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** The rules by key, and every version of one rule in any status. */
export interface RulesPort {
  rules(): Promise<Result<readonly RuleSummary[]>>;
  versionsOf(ruleKey: string): Promise<Result<readonly RuleVersion[]>>;
}

/** The versions in force on a date (published or superseded), by rule key, a page at a time. */
export interface InForcePort {
  inForce(query: {
    asOf: string;
    ruleKey?: string;
    limit: number;
    after?: string;
  }): Promise<Result<readonly RuleVersion[]>>;
}

/** One version, its citations, the clauses they cite and its relations either way. */
export interface VersionPort {
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
  citations(ruleVersionId: string): Promise<Result<readonly Citation[]>>;
  clause(clauseId: string): Promise<Result<ClauseDetail>>;
  relations(query: { from?: string; to?: string }): Promise<Result<readonly RuleRelation[]>>;
}

export type RuleVersionsPort = RulesPort & InForcePort & VersionPort;

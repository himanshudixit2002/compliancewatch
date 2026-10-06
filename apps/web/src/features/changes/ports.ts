import type { ChangeImpact } from "@/entities/applicability/types";
import type { Business } from "@/entities/business/types";
import type { RuleChangePage } from "@/entities/change/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import type { Result } from "@/server/result";

/**
 * What the changes screen needs: the rulebook's published changes a page at a time (the same for
 * every tenant), what a change means for the tenant's businesses (its impact, a page of clients
 * at a time), the cited clauses, and the business the page is about.
 */
export interface ChangesPort {
  feed(query: { limit: number; cursor?: string }): Promise<Result<RuleChangePage>>;
  impact(
    ruleVersionId: string,
    query: { limit: number; cursor?: string },
  ): Promise<Result<ChangeImpact>>;
  clause(clauseId: string): Promise<Result<ClauseDetail>>;
  business(businessId: string): Promise<Result<Business>>;
}

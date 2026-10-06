import type {
  ResolveInput,
  ReviewItem,
  ReviewItemPage,
  ReviewStatus,
} from "@/entities/applicability/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/**
 * What the decision review screen needs from the applicability engine: one tenant's review items
 * (the decisions a person has to settle), oldest first, a page at a time, and the settling of one,
 * for the tenant the lookup names (the documented cross-tenant exception of these two routes).
 */
export interface ReviewQueuePort {
  items(query: {
    status?: ReviewStatus;
    limit: number;
    cursor?: string;
  }): Promise<Result<ReviewItemPage>>;
  resolve(itemId: string, input: ResolveInput, resolvedBy: string): Promise<Result<ReviewItem>>;
}

/** And the rule versions the items are about, from the rulebook, to name them. */
export interface ReviewVersionsPort {
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
}

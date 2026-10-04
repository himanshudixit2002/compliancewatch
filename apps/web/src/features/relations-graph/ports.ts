import type { RuleRelation } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** What the graph reads: a version, and the relations at a version or an entity. */
export interface GraphPort {
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
  relations(query: {
    from?: string;
    to?: string;
    toEntity?: string;
    publishedOnly: boolean;
  }): Promise<Result<readonly RuleRelation[]>>;
}

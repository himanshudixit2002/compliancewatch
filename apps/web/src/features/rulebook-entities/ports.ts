import type {
  CanonicalEntity,
  EntityResolution,
  EntityType,
  MentionedClause,
  RuleRelation,
} from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** What the canonical entity tools need from the rulebook's knowledge graph. */
export interface EntitiesPort {
  resolve(entityType: EntityType, name: string): Promise<Result<EntityResolution>>;
  entity(entityId: string): Promise<Result<CanonicalEntity>>;
  clauses(
    entityId: string,
    query: { asOf?: string; limit: number },
  ): Promise<Result<readonly MentionedClause[]>>;
  relationsTo(entityId: string): Promise<Result<readonly RuleRelation[]>>;
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
}

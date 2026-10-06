import type { EntityType, MentionGroup, ReviewItem } from "@/entities/rulebook/types";
import type { Result } from "@/server/result";

/** Where a page of groups starts: after this group, in the rulebook's (type, name) order. */
export interface GroupCursor {
  entityType: EntityType;
  name: string;
}

/** The entity review queue's reads; the decisions go through server/api/rulebook-write.ts. */
export interface EntityReviewPort {
  /** Open groups in (type, name) order, of one type or every type, after a cursor. */
  groups(query: {
    entityType: EntityType | null;
    after: GroupCursor | null;
    limit: number;
  }): Promise<Result<MentionGroup[]>>;
  /** Every open mention of one group, with the review ids a decision can name. */
  items(entityType: EntityType, name: string): Promise<Result<ReviewItem[]>>;
}

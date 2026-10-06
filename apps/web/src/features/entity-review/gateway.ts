import "server-only";

import { mentionGroupFromDto, reviewItemFromDto } from "@/entities/rulebook/mappers";
import type { EntityType, MentionGroup, ReviewItem } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { EntityReviewPort, GroupCursor } from "./ports";

/**
 * The entity review queue over the typed rulebook client: the open groups and one group's
 * mentions. Both are read fresh on every visit: the pipeline fills the queue outside this app
 * and an analyst's decision empties it, so a cached page would show groups already decided
 * (D-036). No tenant header and no token: in header mode the rulebook serves the queues to any
 * caller, and with tokens it reads the analyst's role from the bearer.
 */
export class EntityReviewGateway implements EntityReviewPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async groups(query: {
    entityType: EntityType | null;
    after: GroupCursor | null;
    limit: number;
  }): Promise<Result<MentionGroup[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/entities", {
        params: {
          query: {
            limit: query.limit,
            ...(query.entityType === null ? {} : { entity_type: query.entityType }),
            ...(query.after === null
              ? {}
              : { after_type: query.after.entityType, after_name: query.after.name }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (groups) => groups.map(mentionGroupFromDto));
  }

  async items(entityType: EntityType, name: string): Promise<Result<ReviewItem[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/entities/items", {
        params: { query: { entity_type: entityType, proposed_name: name } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (items) => items.map(reviewItemFromDto));
  }
}

/** The gateway for the entity review pages; tests add fetchImpl. */
export function entityReviewGateway(
  ctx: Pick<ClientContext, "fetchImpl"> = {},
): EntityReviewGateway {
  return new EntityReviewGateway(ctx);
}

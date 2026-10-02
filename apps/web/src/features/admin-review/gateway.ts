import "server-only";

import {
  rulebookClient,
  type ClientContext,
} from "@/server/api/services";
import type { RulebookClient } from "@/server/api/rulebook-write";
import { uncachedRead } from "@/server/cache";
import { call } from "@/server/api/client";
import { mapBody, type Result } from "@/server/result";
import type { EntityType } from "@/entities/rulebook/types";
import type { EntityGroupOut, RelationCandidateOut } from "./ports";

export class ReviewReadGateway {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async entityGroups(): Promise<Result<EntityGroupOut[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/entities", {
        params: { query: { limit: 200 } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (groups) => groups as EntityGroupOut[]);
  }

  async openCandidates(): Promise<Result<RelationCandidateOut[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/relations", {
        params: { query: { status: "open", limit: 200 } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (candidates) => candidates as RelationCandidateOut[]);
  }

  async groupItems(
    entityType: EntityType,
    proposedName: string,
  ): Promise<Result<Array<{ review_id: string; document_id: string; clause_id: string; mention_text: string; span_start: number; span_end: number; reason: string }>>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/entities/items", {
        params: { query: { entity_type: entityType, proposed_name: proposedName } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (items) => items as Array<{ review_id: string; document_id: string; clause_id: string; mention_text: string; span_start: number; span_end: number; reason: string }>);
  }
}

export function reviewReadGateway(
  ctx: Pick<ClientContext, "fetchImpl"> = {},
): ReviewReadGateway {
  return new ReviewReadGateway(ctx);
}
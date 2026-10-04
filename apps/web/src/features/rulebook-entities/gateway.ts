import "server-only";

import {
  entityFromDto,
  mentionedClauseFromDto,
  relationFromDto,
  resolutionFromDto,
} from "@/entities/rulebook/mappers";
import type {
  CanonicalEntity,
  EntityResolution,
  EntityType,
  MentionedClause,
  RuleRelation,
} from "@/entities/rulebook/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { EntitiesPort } from "./ports";

/** The most relations to one entity a page asks for; the route serves up to 500. */
export const RELATIONS_LIMIT = 200;

/**
 * The rulebook's knowledge graph over the typed client: resolving a name, an entity, the clauses
 * that mention it, the relations that point at it and the versions they come from. No tenant
 * header and no token (open reads). Entities change when an analyst decides a review group (a
 * new entity, a new alias), so nothing here is cached.
 */
export class EntitiesGateway implements EntitiesPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async resolve(entityType: EntityType, name: string): Promise<Result<EntityResolution>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/entities/resolve", {
        params: { query: { type: entityType, name } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, resolutionFromDto);
  }

  async entity(entityId: string): Promise<Result<CanonicalEntity>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/entities/{entity_id}", {
        params: { path: { entity_id: entityId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, entityFromDto);
  }

  async clauses(
    entityId: string,
    query: { asOf?: string; limit: number },
  ): Promise<Result<readonly MentionedClause[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/entities/{entity_id}/clauses", {
        params: {
          path: { entity_id: entityId },
          query: { limit: query.limit, ...(query.asOf === undefined ? {} : { as_of: query.asOf }) },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(mentionedClauseFromDto));
  }

  async relationsTo(entityId: string): Promise<Result<readonly RuleRelation[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/relations", {
        params: {
          query: { to_entity_id: entityId, published_only: false, limit: RELATIONS_LIMIT },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(relationFromDto));
  }

  async version(ruleVersionId: string): Promise<Result<RuleVersion>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rule-versions/{rule_version_id}", {
        params: { path: { rule_version_id: ruleVersionId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, ruleVersionFromDto);
  }
}

/** The gateway for a page; tests add fetchImpl. */
export function entitiesGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): EntitiesGateway {
  return new EntitiesGateway(ctx);
}

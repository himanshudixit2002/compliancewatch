import "server-only";

import { relationFromDto } from "@/entities/rulebook/mappers";
import type { RuleRelation } from "@/entities/rulebook/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { GraphPort } from "./ports";

/** The most relations one read asks for; the route serves up to 500. */
export const RELATIONS_LIMIT = 200;

/**
 * The relations around a rule version over the typed client, with no tenant header and no token.
 * Relations are added while versions are drafts and versions move through review, so nothing is
 * cached.
 */
export class GraphGateway implements GraphPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
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

  async relations(query: {
    from?: string;
    to?: string;
    toEntity?: string;
    publishedOnly: boolean;
  }): Promise<Result<readonly RuleRelation[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/relations", {
        params: {
          query: {
            published_only: query.publishedOnly,
            limit: RELATIONS_LIMIT,
            ...(query.from === undefined ? {} : { from_rule_version_id: query.from }),
            ...(query.to === undefined ? {} : { to_rule_version_id: query.to }),
            ...(query.toEntity === undefined ? {} : { to_entity_id: query.toEntity }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(relationFromDto));
  }
}

/** The gateway for a page; tests add fetchImpl. */
export function graphGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): GraphGateway {
  return new GraphGateway(ctx);
}

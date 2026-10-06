import "server-only";

import { changeImpactFromDto } from "@/entities/applicability/mappers";
import type { ChangeImpact } from "@/entities/applicability/types";
import { businessFromDto } from "@/entities/business/mappers";
import type { Business } from "@/entities/business/types";
import { ruleChangePageFromDto } from "@/entities/change/mappers";
import type { RuleChangePage } from "@/entities/change/types";
import { clauseDetailFromDto } from "@/entities/rulebook/mappers";
import type { ClauseDetail } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import {
  applicabilityEngineClient,
  profileClient,
  rulebookClient,
  type ApplicabilityEngineClient,
  type ClientContext,
  type ProfileClient,
  type RulebookClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { ChangesPort } from "./ports";

/**
 * The changes screen over the typed clients: the rulebook's feed (the public `GET /v1/changes`,
 * no tenant, not cached, since a publication may land at any moment), the engine's impact of a
 * change for the tenant (`GET /v1/changes/{id}/impact`, x-tenant-id, never cached), a cited
 * clause (kept five minutes under its tag) and the business from the profile service.
 */
export class ChangesGateway implements ChangesPort {
  private readonly rulebook: RulebookClient;
  private readonly engine: ApplicabilityEngineClient;
  private readonly profile: ProfileClient;

  constructor(ctx: ClientContext) {
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
    this.engine = applicabilityEngineClient(ctx);
    this.profile = profileClient(ctx);
  }

  async feed(query: { limit: number; cursor?: string }): Promise<Result<RuleChangePage>> {
    const result = await call(
      this.rulebook.GET("/v1/changes", {
        params: {
          query: {
            limit: query.limit,
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, ruleChangePageFromDto);
  }

  async impact(
    ruleVersionId: string,
    query: { limit: number; cursor?: string },
  ): Promise<Result<ChangeImpact>> {
    const result = await call(
      this.engine.GET("/v1/changes/{rule_version_id}/impact", {
        params: {
          path: { rule_version_id: ruleVersionId },
          query: {
            limit: query.limit,
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, changeImpactFromDto);
  }

  async clause(clauseId: string): Promise<Result<ClauseDetail>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/clauses/{clause_id}", {
        params: { path: { clause_id: clauseId } },
        ...cachedRead([tags.rulebook.clause(clauseId)]),
      }),
    );
    return mapBody(result, clauseDetailFromDto);
  }

  async business(businessId: string): Promise<Result<Business>> {
    const result = await call(
      this.profile.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, businessFromDto);
  }
}

export function changesGateway(ctx: ClientContext): ChangesGateway {
  return new ChangesGateway(ctx);
}

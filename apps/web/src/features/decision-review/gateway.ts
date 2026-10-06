import "server-only";

import {
  resolveToDto,
  reviewItemFromDto,
  reviewItemPageFromDto,
} from "@/entities/applicability/mappers";
import type {
  ResolveInput,
  ReviewItem,
  ReviewItemPage,
  ReviewStatus,
} from "@/entities/applicability/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import {
  applicabilityEngineClient,
  rulebookClient,
  type ApplicabilityEngineClient,
  type ClientContext,
  type RulebookClient,
} from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { ReviewQueuePort, ReviewVersionsPort } from "./ports";

/**
 * The review queue over the typed engine client, for the tenant the admin lookup names
 * (`ClientContext.tenantId`, sent as x-tenant-id): on the two review routes a regulatory user names
 * the tenant reviewed rather than their own. The items are tenant data and never cached; the
 * versions they are about are read from the rulebook, with no tenant.
 */
export class DecisionReviewGateway implements ReviewQueuePort, ReviewVersionsPort {
  private readonly engine: ApplicabilityEngineClient;
  private readonly rulebook: RulebookClient;

  constructor(ctx: ClientContext) {
    this.engine = applicabilityEngineClient(ctx);
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
  }

  async items(query: {
    status?: ReviewStatus;
    limit: number;
    cursor?: string;
  }): Promise<Result<ReviewItemPage>> {
    const result = await call(
      this.engine.GET("/v1/applicability-engine/review-items", {
        params: {
          query: {
            limit: query.limit,
            ...(query.status === undefined ? {} : { status: query.status }),
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, reviewItemPageFromDto);
  }

  async resolve(
    itemId: string,
    input: ResolveInput,
    resolvedBy: string,
  ): Promise<Result<ReviewItem>> {
    const result = await call(
      this.engine.POST("/v1/applicability-engine/review-items/{item_id}/resolve", {
        params: { path: { item_id: itemId } },
        body: resolveToDto(input, resolvedBy),
      }),
    );
    return mapBody(result, reviewItemFromDto);
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

/** The gateway acting for the looked-up tenant; tests add fetchImpl. */
export function decisionReviewGateway(ctx: ClientContext): DecisionReviewGateway {
  return new DecisionReviewGateway(ctx);
}

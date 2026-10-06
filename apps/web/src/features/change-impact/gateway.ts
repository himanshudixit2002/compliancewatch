import "server-only";

import { changeImpactFromDto } from "@/entities/applicability/mappers";
import type { Applicability, ChangeImpact } from "@/entities/applicability/types";
import { businessFromDto } from "@/entities/business/mappers";
import type { Business } from "@/entities/business/types";
import { bulkRequestToDto, bulkResultFromDto } from "@/entities/notification/mappers";
import type { BulkNotificationResult } from "@/entities/notification/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { callIdempotent, type Replayable } from "@/server/api/idempotency";
import {
  applicabilityEngineClient,
  notificationClient,
  profileClient,
  rulebookClient,
  type ApplicabilityEngineClient,
  type ClientContext,
  type NotificationClient,
  type ProfileClient,
  type RulebookClient,
} from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, mapResult, type Result } from "@/server/result";
import type { ChangeImpactPort, WriteHeaders } from "./ports";

type KeyHeader = { "Idempotency-Key": string };

/**
 * The affected clients screen over the typed clients: the engine's impact of a change for the
 * session's tenant (x-tenant-id, never cached), the rulebook's version (no tenant), the profile
 * service's business (the client's name) and the notification service's bulk change card, which
 * takes the form's Idempotency-Key and replays its first answer to a repeat (`callIdempotent`).
 */
export class ChangeImpactGateway implements ChangeImpactPort {
  private readonly engine: ApplicabilityEngineClient;
  private readonly rulebook: RulebookClient;
  private readonly profile: ProfileClient;
  private readonly notification: NotificationClient;

  constructor(ctx: ClientContext) {
    this.engine = applicabilityEngineClient(ctx);
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
    this.profile = profileClient(ctx);
    this.notification = notificationClient(ctx);
  }

  async impact(
    ruleVersionId: string,
    query: { result?: Applicability; limit: number; cursor?: string },
  ): Promise<Result<ChangeImpact>> {
    const result = await call(
      this.engine.GET("/v1/changes/{rule_version_id}/impact", {
        params: {
          path: { rule_version_id: ruleVersionId },
          query: {
            limit: query.limit,
            ...(query.result === undefined ? {} : { result: query.result }),
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, changeImpactFromDto);
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

  async business(businessId: string): Promise<Result<Business>> {
    const result = await call(
      this.profile.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, businessFromDto);
  }

  async sendChangeCards(
    ruleVersionId: string,
    businessIds: readonly string[],
    headers: WriteHeaders,
  ): Promise<Result<Replayable<BulkNotificationResult>>> {
    const result = await callIdempotent(
      this.notification.POST("/v1/notification/bulk", {
        params: { header: headers as KeyHeader },
        body: bulkRequestToDto(ruleVersionId, businessIds),
      }),
    );
    if (!result.ok) return result;
    const { replayed } = result.value;
    return mapBody(
      mapResult(result, (answer) => answer.value),
      (value) => ({ value: bulkResultFromDto(value), replayed }),
    );
  }
}

export function changeImpactGateway(ctx: ClientContext): ChangeImpactGateway {
  return new ChangeImpactGateway(ctx);
}

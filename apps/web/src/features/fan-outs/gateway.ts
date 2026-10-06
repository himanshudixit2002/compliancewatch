import "server-only";

import {
  fanOutHoldFromDto,
  fanOutPageFromDto,
  fanOutRunFromDto,
  holdToDto,
} from "@/entities/applicability/mappers";
import type { FanOutHold, FanOutRun, FanOutRunPage } from "@/entities/applicability/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import {
  applicabilityEngineAdminClient,
  rulebookClient,
  type ApplicabilityEngineClient,
  type ClientContext,
  type RulebookClient,
} from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { FanOutPort, FanOutVersionsPort } from "./ports";

/**
 * The fan-out screens over the typed clients: the engine's admin routes (no tenant header; a
 * fan-out belongs to no tenant) and the rulebook's version read. Nothing is cached: a run moves on
 * batch by batch and a control changes it at once. The role is checked by the caller before a
 * control is sent; the engine checks it again once it reads tokens.
 */
export class FanOutsGateway implements FanOutPort, FanOutVersionsPort {
  private readonly engine: ApplicabilityEngineClient;
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.engine = applicabilityEngineAdminClient({ fetchImpl: ctx.fetchImpl });
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
  }

  async list(query: { limit: number; cursor?: string }): Promise<Result<FanOutRunPage>> {
    const result = await call(
      this.engine.GET("/v1/applicability-engine/fan-outs", {
        params: {
          query: {
            limit: query.limit,
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, fanOutPageFromDto);
  }

  async get(ruleVersionId: string): Promise<Result<FanOutRun>> {
    const result = await call(
      this.engine.GET("/v1/applicability-engine/fan-outs/{rule_version_id}", {
        params: { path: { rule_version_id: ruleVersionId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, fanOutRunFromDto);
  }

  async hold(): Promise<Result<FanOutHold>> {
    const result = await call(
      this.engine.GET("/v1/applicability-engine/fan-out-hold", { ...uncachedRead() }),
    );
    return mapBody(result, fanOutHoldFromDto);
  }

  async setHold(held: boolean, reason: string): Promise<Result<FanOutHold>> {
    const result = await call(
      this.engine.PUT("/v1/applicability-engine/fan-out-hold", { body: holdToDto(held, reason) }),
    );
    return mapBody(result, fanOutHoldFromDto);
  }

  async pause(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>> {
    const result = await call(
      this.engine.POST("/v1/applicability-engine/fan-outs/{rule_version_id}/pause", {
        params: { path: { rule_version_id: ruleVersionId } },
        body: { reason },
      }),
    );
    return mapBody(result, fanOutRunFromDto);
  }

  async resume(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>> {
    const result = await call(
      this.engine.POST("/v1/applicability-engine/fan-outs/{rule_version_id}/resume", {
        params: { path: { rule_version_id: ruleVersionId } },
        body: { reason },
      }),
    );
    return mapBody(result, fanOutRunFromDto);
  }

  async cancel(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>> {
    const result = await call(
      this.engine.POST("/v1/applicability-engine/fan-outs/{rule_version_id}/cancel", {
        params: { path: { rule_version_id: ruleVersionId } },
        body: { reason },
      }),
    );
    return mapBody(result, fanOutRunFromDto);
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

/** The gateway for a page or an action; tests pass fetchImpl. */
export function fanOutsGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): FanOutsGateway {
  return new FanOutsGateway(ctx);
}

import "server-only";

import { dryRunReportFromDto, dryRunToDto } from "@/entities/applicability/mappers";
import type { DryRunReport, DryRunRequest } from "@/entities/applicability/types";
import { call } from "@/server/api/client";
import {
  applicabilityEngineAdminClient,
  type ApplicabilityEngineClient,
  type ClientContext,
} from "@/server/api/services";
import { mapBody, type Result } from "@/server/result";
import type { DryRunPort } from "./ports";

/**
 * The dry run over the engine's admin client: no tenant header (the scope names a tenant when it
 * narrows to one), never cached (a dry run reads the profiles as they are now). The admin role is
 * checked by the action before the call; the engine checks it again once it reads tokens.
 */
export class ImpactExplorerGateway implements DryRunPort {
  private readonly engine: ApplicabilityEngineClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.engine = applicabilityEngineAdminClient({ fetchImpl: ctx.fetchImpl });
  }

  async dryRun(request: DryRunRequest): Promise<Result<DryRunReport>> {
    const result = await call(
      this.engine.POST("/v1/applicability-engine/dry-runs", { body: dryRunToDto(request) }),
    );
    return mapBody(result, dryRunReportFromDto);
  }
}

export function impactExplorerGateway(
  ctx: Pick<ClientContext, "fetchImpl"> = {},
): ImpactExplorerGateway {
  return new ImpactExplorerGateway(ctx);
}

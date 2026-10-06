import "server-only";

import { modelRouteFromDto, promptFromDto, usageFromDto } from "@/entities/llm/mappers";
import type { LlmFeature, ModelRoute, Prompt, Usage } from "@/entities/llm/types";
import { call } from "@/server/api/client";
import { llmGatewayClient, type ClientContext, type LlmGatewayClient } from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { LlmRegistryPort } from "./ports";

/**
 * The LLM gateway's prompt registry, model routes and spend, over the typed client built with no
 * session, so no x-tenant-id goes out: the registries belong to no tenant, and the usage route
 * reads its tenant from the header when the query names none, which would turn "a feature's
 * budget" into "the internal tenant's spend" (the operator's own tenant is the internal one). The
 * prompts and the routes change only with a release of the gateway, so they are kept for five
 * minutes under their tags; spend is read fresh.
 */
export class LlmRegistryGateway implements LlmRegistryPort {
  private readonly gateway: LlmGatewayClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.gateway = llmGatewayClient({ session: null, fetchImpl: ctx.fetchImpl });
  }

  async prompts(): Promise<Result<Prompt[]>> {
    const result = await call(
      this.gateway.GET("/v1/llm-gateway/prompts", { ...cachedRead([tags.llm.prompts()]) }),
    );
    return mapBody(result, (prompts) => prompts.map(promptFromDto));
  }

  async models(): Promise<Result<ModelRoute[]>> {
    const result = await call(
      this.gateway.GET("/v1/llm-gateway/models", { ...cachedRead([tags.llm.models()]) }),
    );
    return mapBody(result, (routes) => routes.map(modelRouteFromDto));
  }

  async usage(query: {
    tenantId?: string;
    feature?: LlmFeature;
    month: string;
  }): Promise<Result<Usage>> {
    const result = await call(
      this.gateway.GET("/v1/llm-gateway/usage", {
        params: {
          query: {
            month: query.month,
            ...(query.tenantId === undefined ? {} : { tenant_id: query.tenantId }),
            ...(query.feature === undefined ? {} : { feature: query.feature }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, usageFromDto);
  }
}

/** The gateway for the LLM gateway pages; tests add fetchImpl. */
export function llmRegistryGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): LlmRegistryGateway {
  return new LlmRegistryGateway(ctx);
}

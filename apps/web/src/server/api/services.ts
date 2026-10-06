import "server-only";

import type {
  applicabilityEngine,
  identity,
  llmGateway,
  notification,
  obligation,
  profile,
  qa,
  rulebook,
} from "@compliancewatch/contracts/openapi";
import type { Client } from "openapi-fetch";
import type { Principal } from "@/shared/config/roles";
import type { ServiceName } from "@/shared/config/services";
import { getEnv, serviceUrl } from "../env";
import {
  TENANT_HEADER,
  createServiceClient,
  type FetchImpl,
  type ServiceClientOptions,
} from "./client";

/**
 * The client factories the feature gateways build on, one per service with a committed spec.
 * Each takes a `ClientContext`: the session (its tenant id goes out as x-tenant-id on the
 * tenant-scoped services), an optional tenant override for admin lookups (the only way a
 * request carries a tenant other than the session's), and the fetch to use (tests inject one).
 *
 *   identity, profile, notification, llm-gateway, obligation, qa,   x-tenant-id from the session
 *   applicability-engine
 *   rulebook                                                         no tenant header
 *
 * Rulebook writes go through ./rulebook-write.ts, the only module that sends the write and
 * review tokens. Base URLs and the timeout come from the validated environment (server/env.ts).
 */
export interface ClientPrincipal extends Principal {
  userId: string;
  tenantId: string;
}

export interface ClientContext {
  /** The signed-in user, or null for a call that carries no tenant. */
  session: ClientPrincipal | null;
  /** Admin lookups only: the tenant to act for instead of the session's. */
  tenantId?: string;
  fetchImpl?: FetchImpl;
}

export type IdentityClient = Client<identity.paths>;
export type ProfileClient = Client<profile.paths>;
export type NotificationClient = Client<notification.paths>;
export type LlmGatewayClient = Client<llmGateway.paths>;
export type ObligationClient = Client<obligation.paths>;
export type QaClient = Client<qa.paths>;
export type ApplicabilityEngineClient = Client<applicabilityEngine.paths>;
export type RulebookClient = Client<rulebook.paths>;

/** The tenant a request acts for: the override, else the session's. */
export function tenantIdOf(ctx: ClientContext): string | undefined {
  return ctx.tenantId ?? ctx.session?.tenantId;
}

function tenantHeaders(ctx: ClientContext): Record<string, string> {
  const tenantId = tenantIdOf(ctx);
  return tenantId === undefined ? {} : { [TENANT_HEADER]: tenantId };
}

function optionsFor(
  service: ServiceName,
  ctx: Pick<ClientContext, "fetchImpl">,
  headers: Record<string, string>,
): ServiceClientOptions {
  const env = getEnv();
  return {
    service,
    baseUrl: serviceUrl(service, env),
    timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
    fetchImpl: ctx.fetchImpl,
    headers,
  };
}

export function identityClient(ctx: ClientContext): IdentityClient {
  return createServiceClient<identity.paths>(optionsFor("identity", ctx, tenantHeaders(ctx)));
}

export function profileClient(ctx: ClientContext): ProfileClient {
  return createServiceClient<profile.paths>(optionsFor("profile", ctx, tenantHeaders(ctx)));
}

export function notificationClient(ctx: ClientContext): NotificationClient {
  return createServiceClient<notification.paths>(
    optionsFor("notification", ctx, tenantHeaders(ctx)),
  );
}

export function llmGatewayClient(ctx: ClientContext): LlmGatewayClient {
  return createServiceClient<llmGateway.paths>(optionsFor("llm-gateway", ctx, tenantHeaders(ctx)));
}

export function obligationClient(ctx: ClientContext): ObligationClient {
  return createServiceClient<obligation.paths>(optionsFor("obligation", ctx, tenantHeaders(ctx)));
}

export function qaClient(ctx: ClientContext): QaClient {
  return createServiceClient<qa.paths>(optionsFor("qa", ctx, tenantHeaders(ctx)));
}

/**
 * The engine's decisions and a change's impact are the tenant's: every call carries x-tenant-id.
 * The fan-out and dry-run routes name no tenant and belong to the admin tools, which do not use
 * this factory yet.
 */
export function applicabilityEngineClient(ctx: ClientContext): ApplicabilityEngineClient {
  return createServiceClient<applicabilityEngine.paths>(
    optionsFor("applicability-engine", ctx, tenantHeaders(ctx)),
  );
}

/** The rulebook holds regulatory records shared by every tenant: reads carry no tenant header. */
export function rulebookClient(ctx: Pick<ClientContext, "fetchImpl"> = {}): RulebookClient {
  return createServiceClient<rulebook.paths>(optionsFor("rulebook", ctx, {}));
}

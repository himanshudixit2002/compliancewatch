import "server-only";

import type {
  applicabilityEngine,
  identity,
  llmGateway,
  notification,
  obligation,
  pipeline,
  profile,
  qa,
  rulebook,
} from "@compliancewatch/contracts/openapi";
import type { Client } from "openapi-fetch";
import type { Principal } from "@/shared/config/roles";
import type { ServiceName } from "@/shared/config/services";
import { getEnv, serviceUrl } from "../env";
import {
  AUTHORIZATION_HEADER,
  TENANT_HEADER,
  createServiceClient,
  type FetchImpl,
  type ServiceClientOptions,
} from "./client";

/**
 * The client factories the feature gateways build on, one per service with a committed spec.
 * Each takes a `ClientContext`: the session (its tenant id goes out as x-tenant-id and its
 * identity token as Authorization: Bearer on the tenant-scoped services), an optional tenant
 * override for admin lookups (the only way a request carries a tenant other than the session's;
 * it goes without the bearer), and the fetch to use (tests inject one).
 *
 *   identity, profile, notification, llm-gateway, obligation, qa,   x-tenant-id and the bearer
 *   applicability-engine                                            from the session
 *   applicability-engine's admin routes (fan-outs, the hold, dry      no tenant header
 *   runs), through applicabilityEngineAdminClient
 *   rulebook                                                         no tenant header
 *   pipeline                                                         no tenant header
 *
 * Rulebook writes go through ./rulebook-write.ts, the only module that sends the review token,
 * and the pipeline's writes through ./pipeline-write.ts, the only one that sends it the shared
 * write token. Base URLs and the timeout come from the validated environment (server/env.ts).
 */
export interface ClientPrincipal extends Principal {
  userId: string;
  tenantId: string;
  /** Identity's access token for the services; absent only for a session without one. */
  cwToken?: string;
}

export interface ClientContext {
  /** The signed-in user, or null for a call that carries no tenant. */
  session: ClientPrincipal | null;
  /** Admin lookups only: the tenant to act for instead of the session's. */
  tenantId?: string;
  /**
   * Send the session's bearer with another tenant's header too: for routes that read the
   * tenant from the header without comparing it with the token (the engine's review routes,
   * whose regulatory caller names the tenant reviewed and must be named by a token to settle).
   */
  bearerWithOverride?: true;
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
export type PipelineClient = Client<pipeline.paths>;

/** The tenant a request acts for: the override, else the session's. */
export function tenantIdOf(ctx: ClientContext): string | undefined {
  return ctx.tenantId ?? ctx.session?.tenantId;
}

function tenantHeaders(ctx: ClientContext): Record<string, string> {
  const tenantId = tenantIdOf(ctx);
  return tenantId === undefined ? {} : { [TENANT_HEADER]: tenantId };
}

/**
 * `Authorization: Bearer <identity token>` on every call made for a session, with x-tenant-id
 * equal to the token's tenant (the services refuse a header naming another tenant once they
 * read tokens). An admin lookup of another tenant (`ctx.tenantId`) therefore goes without the
 * bearer, as the services' tenant routes take it in header and dual mode, until the admin
 * routes of W13 name the tenant themselves (D-069 in docs/web/decisions.md).
 */
function authHeaders(ctx: ClientContext): Record<string, string> {
  const token = ctx.session?.cwToken;
  if (token === undefined || token === "") return {};
  if (
    ctx.tenantId !== undefined &&
    ctx.tenantId !== ctx.session?.tenantId &&
    ctx.bearerWithOverride !== true
  ) {
    return {};
  }
  return { [AUTHORIZATION_HEADER]: `Bearer ${token}` };
}

/** The headers of a call made for the session: its tenant, and its token when it has one. */
function sessionHeaders(ctx: ClientContext): Record<string, string> {
  return { ...tenantHeaders(ctx), ...authHeaders(ctx) };
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
  return createServiceClient<identity.paths>(optionsFor("identity", ctx, sessionHeaders(ctx)));
}

export function profileClient(ctx: ClientContext): ProfileClient {
  return createServiceClient<profile.paths>(optionsFor("profile", ctx, sessionHeaders(ctx)));
}

export function notificationClient(ctx: ClientContext): NotificationClient {
  return createServiceClient<notification.paths>(
    optionsFor("notification", ctx, sessionHeaders(ctx)),
  );
}

export function llmGatewayClient(ctx: ClientContext): LlmGatewayClient {
  return createServiceClient<llmGateway.paths>(optionsFor("llm-gateway", ctx, sessionHeaders(ctx)));
}

export function obligationClient(ctx: ClientContext): ObligationClient {
  return createServiceClient<obligation.paths>(optionsFor("obligation", ctx, sessionHeaders(ctx)));
}

export function qaClient(ctx: ClientContext): QaClient {
  return createServiceClient<qa.paths>(optionsFor("qa", ctx, sessionHeaders(ctx)));
}

/**
 * The engine's decisions, a change's impact and the review queue are a tenant's: every call
 * carries x-tenant-id (the review queue's admin lookup names the reviewed tenant through
 * `ctx.tenantId`). The fan-out, hold and dry-run routes name no tenant: they go through
 * `applicabilityEngineAdminClient`.
 */
export function applicabilityEngineClient(ctx: ClientContext): ApplicabilityEngineClient {
  return createServiceClient<applicabilityEngine.paths>(
    optionsFor("applicability-engine", ctx, sessionHeaders(ctx)),
  );
}

/**
 * The engine's admin routes that belong to no tenant: the fan-outs, the global hold and dry
 * runs. A fan-out runs over every tenant, so no tenant header goes out, whoever is signed in; the
 * session's bearer does, since outside header mode the engine settles a control or a dry run
 * only for an admin a token names. The admin tools check the role before they call.
 */
export function applicabilityEngineAdminClient(
  ctx: Partial<Pick<ClientContext, "session" | "fetchImpl">> = {},
): ApplicabilityEngineClient {
  return createServiceClient<applicabilityEngine.paths>(
    optionsFor("applicability-engine", ctx, authHeaders({ session: ctx.session ?? null })),
  );
}

/** The rulebook holds regulatory records shared by every tenant: reads carry no tenant header. */
export function rulebookClient(ctx: Pick<ClientContext, "fetchImpl"> = {}): RulebookClient {
  return createServiceClient<rulebook.paths>(optionsFor("rulebook", ctx, {}));
}

/**
 * The pipeline's source manager and operations routes hold regulatory records of no tenant:
 * reads carry no tenant header. Its writes go through ./pipeline-write.ts.
 */
export function pipelineClient(ctx: Pick<ClientContext, "fetchImpl"> = {}): PipelineClient {
  return createServiceClient<pipeline.paths>(optionsFor("pipeline", ctx, {}));
}

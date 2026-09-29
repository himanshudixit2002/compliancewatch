import "server-only";

import type {
  identity,
  llmGateway,
  notification,
  obligation,
  profile,
  qa,
  rulebook,
} from "@compliancewatch/contracts/openapi";
import type { Client } from "openapi-fetch";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import { isRegulatory, type Principal } from "@/shared/config/roles";
import type { ServiceName } from "@/shared/config/services";
import { getEnv, serviceUrl } from "../env";
import { err, ok, type ApiError, type Result } from "../result";
import {
  TENANT_HEADER,
  WRITE_TOKEN_HEADER,
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
 *   identity, profile, notification, llm-gateway, obligation, qa   x-tenant-id from the session
 *   rulebook                                                        no tenant header
 *   rulebookAdmin                                                   x-cw-write-token, after a
 *                                                                   regulatory-role check
 *
 * The write token never leaves this module and never reaches a client without that check;
 * when CW_WEB_RULEBOOK_WRITE_TOKEN is unset the factory answers an "unavailable" Result so an
 * admin action reports "not configured" instead of calling the service. Base URLs and the
 * timeout come from the validated environment (server/env.ts).
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

/** The rulebook holds regulatory records shared by every tenant: reads carry no tenant header. */
export function rulebookClient(ctx: Pick<ClientContext, "fetchImpl"> = {}): RulebookClient {
  return createServiceClient<rulebook.paths>(optionsFor("rulebook", ctx, {}));
}

/** An ApiError for a failure decided here, before any request: no request id, a web-local problem. */
function localError(kind: ApiError["kind"], slug: string, title: string, detail: string): ApiError {
  const status = kind === "forbidden" ? 403 : 503;
  return {
    kind,
    status,
    requestId: "",
    problem: { type: `${PROBLEM_TYPE_PREFIX}${slug}`, title, status, detail },
    message: title,
  };
}

/**
 * The rulebook client that may write. It exists only for a session with a regulatory role and
 * only while the write token is configured; each write route still answers 401 when the token
 * is wrong. Callers pass the Result straight through: `if (!admin.ok) return admin;`.
 */
export function rulebookAdmin(ctx: ClientContext): Result<RulebookClient> {
  if (!isRegulatory(ctx.session)) {
    return err(
      localError(
        "forbidden",
        "web-regulatory-role-required",
        "Regulatory role required",
        "Rulebook writes are made by analysts, reviewers and admins only.",
      ),
    );
  }
  const token = getEnv().CW_WEB_RULEBOOK_WRITE_TOKEN;
  if (token === undefined) {
    return err(
      localError(
        "unavailable",
        "web-write-token-missing",
        "Rulebook writes are not configured",
        "Set CW_WEB_RULEBOOK_WRITE_TOKEN to the rulebook's write token.",
      ),
    );
  }
  return ok(
    createServiceClient<rulebook.paths>(
      optionsFor("rulebook", ctx, { [WRITE_TOKEN_HEADER]: token }),
    ),
  );
}

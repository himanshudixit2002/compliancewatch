import "server-only";

import type { identity } from "@compliancewatch/contracts/openapi";
import { epochSeconds, sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { isRole, isTenantKind } from "@/shared/config/roles";
import type { Role } from "@/shared/config/roles";
import { call, createServiceClient, type FetchImpl } from "../api/client";
import { getEnv, serviceUrl, type AuthProviderName, type WebEnv } from "../env";
import { isProblem, webError, type ApiError } from "../result";
import type { ProviderSession } from "./provider";

/**
 * The session exchange with the identity service: a verified provider session becomes the
 * claims the cookie carries, or one of the answers the sign-in flow acts on. The routes:
 *
 *   POST /v1/identity/sessions {provider_token}      an access token for the services
 *   POST /v1/identity/tenants  {kind, name, ...}     sign-up: the tenant, its first user and a session
 *   GET  /v1/identity/me                             the user, re-read with the bearer token
 *
 * The exchange answers everything the cookie needs (the tenant and its kind, the user and the
 * display name, the roles, the second factor, the session version), so no second call is made
 * before the cookie is written. `/me` is for later: the account page's profile fields and the
 * proxy's re-read, where a 401 means the session was revoked.
 */
export type SessionOut = identity.components["schemas"]["SessionOut"];
export type MeOut = identity.components["schemas"]["MeOut"];
export type SignUpKind = "business" | "ca_firm";

export type ExchangeOutcome =
  | { kind: "signed-in"; claims: SessionClaims }
  | { kind: "needs-sign-up" }
  | { kind: "needs-mfa" }
  | { kind: "user-disabled" }
  | { kind: "tenant-deleting" }
  | { kind: "subject-registered" }
  | { kind: "provider-unavailable"; error: ApiError }
  | { kind: "failed"; error: ApiError };

export interface SessionDeps {
  env?: WebEnv;
  fetchImpl?: FetchImpl;
  now?: Date;
}

function identityClient(deps: SessionDeps, token?: string) {
  const env = deps.env ?? getEnv();
  return createServiceClient<identity.paths>({
    service: "identity",
    baseUrl: serviceUrl("identity", env),
    timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
    fetchImpl: deps.fetchImpl,
    headers: token === undefined ? {} : { authorization: `Bearer ${token}` },
  });
}

/** The cookie's claims from what identity answered and the provider session behind it. */
export function claimsFromSessionOut(
  session: SessionOut,
  provider: ProviderSession,
  providerName: AuthProviderName,
  now: Date,
  ttlSeconds: number,
): SessionClaims | null {
  if (!isTenantKind(session.tenant_kind)) return null;
  const roles = session.roles.filter((role): role is Role => isRole(role));
  if (roles.length === 0) return null;
  const displayName = session.display_name.trim() || fallbackName(session);
  return {
    userId: session.user_id,
    tenantId: session.tenant_id,
    tenantKind: session.tenant_kind,
    roles,
    displayName,
    mfa: session.mfa,
    sv: session.session_version,
    provider: providerName,
    ...sessionWindow(now, ttlSeconds),
    cwToken: session.access_token,
    cwTokenExpiresAt: epochSeconds(now) + session.expires_in,
    providerRefreshToken: provider.refreshToken,
    providerAccessToken: provider.accessToken,
    providerAccessExpiresAt: provider.expiresAt,
    checkedAt: epochSeconds(now),
  };
}

/** How long a provider access token must still have for a factor call made with it. */
export const PROVIDER_TOKEN_MARGIN_SECONDS = 30;

/**
 * The provider session the cookie carries: null without one, or once its access token has
 * under `marginSeconds` left, when a refresh at the provider is due (an action or the proxy
 * does it and writes the rotated pair back; a render never refreshes, since it cannot write).
 * The level is the session's `mfa`; the subject is not kept in the cookie.
 */
export function providerSessionOf(
  claims: SessionClaims,
  now: number,
  marginSeconds: number = PROVIDER_TOKEN_MARGIN_SECONDS,
): ProviderSession | null {
  if (
    claims.providerAccessToken === undefined ||
    claims.providerAccessExpiresAt === undefined ||
    claims.providerRefreshToken === undefined
  ) {
    return null;
  }
  if (claims.providerAccessExpiresAt - now < marginSeconds) return null;
  return {
    accessToken: claims.providerAccessToken,
    refreshToken: claims.providerRefreshToken,
    expiresAt: claims.providerAccessExpiresAt,
    aal: claims.mfa ? "aal2" : "aal1",
    subject: "",
  };
}

/**
 * The claims with a provider session that rotated (a refresh, a factor verify): GoTrue spends
 * the old refresh token, so the new pair must reach the cookie before anything else uses it.
 */
export function withProviderSession(
  claims: SessionClaims,
  session: ProviderSession,
): SessionClaims {
  const next: SessionClaims = {
    ...claims,
    providerAccessToken: session.accessToken,
    providerAccessExpiresAt: session.expiresAt,
    providerRefreshToken: session.refreshToken,
  };
  delete next.refreshNotBefore;
  return next;
}

/** A person who gave no name is shown by the first eight characters of their user id. */
function fallbackName(session: SessionOut): string {
  return `User ${session.user_id.slice(0, 8)}`;
}

function refusal(error: ApiError): ExchangeOutcome {
  if (isProblem(error, "identity-user-not-provisioned")) return { kind: "needs-sign-up" };
  if (isProblem(error, "identity-mfa-required")) return { kind: "needs-mfa" };
  if (isProblem(error, "identity-user-disabled")) return { kind: "user-disabled" };
  if (isProblem(error, "identity-tenant-deleting")) return { kind: "tenant-deleting" };
  if (isProblem(error, "identity-subject-registered")) return { kind: "subject-registered" };
  if (isProblem(error, "identity-provider-unavailable") || error.kind === "network") {
    return { kind: "provider-unavailable", error };
  }
  return { kind: "failed", error };
}

function signedIn(
  session: SessionOut | undefined,
  provider: ProviderSession,
  providerName: AuthProviderName,
  deps: SessionDeps,
): ExchangeOutcome {
  const env = deps.env ?? getEnv();
  const claims =
    session === undefined
      ? null
      : claimsFromSessionOut(
          session,
          provider,
          providerName,
          deps.now ?? new Date(),
          env.CW_WEB_SESSION_TTL_SECONDS,
        );
  if (claims === null) {
    return {
      kind: "failed",
      error: webError(
        "server",
        "web-session-shape",
        "The identity service answered a session this app cannot read",
      ),
    };
  }
  return { kind: "signed-in", claims };
}

/** `POST /v1/identity/sessions` for the provider session, mapped to what the flow does next. */
export async function exchangeSession(
  provider: ProviderSession,
  providerName: AuthProviderName,
  deps: SessionDeps = {},
): Promise<ExchangeOutcome> {
  const result = await call(
    identityClient(deps).POST("/v1/identity/sessions", {
      body: { provider_token: provider.accessToken },
    }),
  );
  if (!result.ok) return refusal(result.error);
  return signedIn(result.value, provider, providerName, deps);
}

export interface SignUpInput {
  kind: SignUpKind;
  name: string;
  displayName: string;
}

/** `POST /v1/identity/tenants`: the new tenant's first session, or the refusal. */
export async function signUpTenant(
  provider: ProviderSession,
  providerName: AuthProviderName,
  input: SignUpInput,
  deps: SessionDeps = {},
): Promise<ExchangeOutcome> {
  const result = await call(
    identityClient(deps).POST("/v1/identity/tenants", {
      body: {
        kind: input.kind,
        name: input.name,
        provider_token: provider.accessToken,
        display_name: input.displayName,
      },
    }),
  );
  if (!result.ok) return refusal(result.error);
  return signedIn(result.value?.session, provider, providerName, deps);
}

export type MeOutcome =
  | { kind: "ok"; me: MeOut }
  | { kind: "revoked"; error: ApiError }
  /** Identity runs header mode and reads no token: nothing can be re-checked there. */
  | { kind: "unverifiable"; error: ApiError }
  | { kind: "failed"; error: ApiError };

/** `GET /v1/identity/me` with the session's token: the user as identity knows them now. */
export async function readMe(
  claims: Pick<SessionClaims, "cwToken" | "tenantId">,
  deps: SessionDeps = {},
): Promise<MeOutcome> {
  if (claims.cwToken === undefined) {
    return {
      kind: "unverifiable",
      error: webError(
        "unauthenticated",
        "web-session-without-token",
        "The session carries no token",
      ),
    };
  }
  const result = await call(
    identityClient(deps, claims.cwToken).GET("/v1/identity/me", {
      headers: { "x-tenant-id": claims.tenantId },
    }),
    { revoked: "report" },
  );
  if (result.ok) {
    if (result.value === undefined) {
      return { kind: "failed", error: webError("server", "web-empty-body", "No answer from /me") };
    }
    return { kind: "ok", me: result.value };
  }
  const { error } = result;
  if (
    isProblem(error, "identity-session-revoked") ||
    isProblem(error, "auth-token-invalid") ||
    isProblem(error, "identity-user-disabled") ||
    isProblem(error, "identity-tenant-deleting")
  ) {
    return { kind: "revoked", error };
  }
  if (isProblem(error, "auth-token-required")) return { kind: "unverifiable", error };
  return { kind: "failed", error };
}

/** The claims brought up to what `/me` says: roles, the second factor, the version, the name. */
export function claimsFromMe(claims: SessionClaims, me: MeOut, now: Date): SessionClaims {
  const roles = me.roles.filter((role): role is Role => isRole(role));
  return {
    ...claims,
    roles: roles.length === 0 ? claims.roles : roles,
    mfa: me.mfa,
    sv: me.session_version,
    displayName: me.display_name.trim() || claims.displayName,
    checkedAt: epochSeconds(now),
  };
}

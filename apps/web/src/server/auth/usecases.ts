import "server-only";

import { epochSeconds } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { getEnv, type WebEnv } from "../env";
import { err, ok, type ApiError, type Result } from "../result";
import type { PendingContact, PendingSignIn, PendingSignUp } from "./pending";
import type { AuthProvider, ProviderSession } from "./provider";
import {
  claimsFromMe,
  exchangeSession,
  readMe,
  signUpTenant,
  type ExchangeOutcome,
  type SessionDeps,
  type SignUpInput,
} from "./sessions";

/**
 * The sign-in flows as the server actions, the callback handler and the proxy run them, with
 * nothing of Next in them (the callers read and write the cookies): what to do once the
 * provider verified a person, how a sign-up or a second factor completes, and how the proxy
 * keeps a session current (a refresh when the token is about to expire, a re-read of /me once
 * the last read is old). Tested without Next in usecases.test.ts.
 */
export type SignInStep =
  /** Write the cookie and go to `next` or the role's home. */
  | { kind: "session"; claims: SessionClaims }
  /** Keep the provider session in cw_pending and go to /sign-up. */
  | { kind: "sign-up"; pending: PendingSignIn }
  /** Keep the provider session in cw_pending and go to /account/mfa. */
  | { kind: "mfa"; pending: PendingSignIn }
  /** Identity refused for good; the form says why. */
  | { kind: "refused"; reason: "user-disabled" | "tenant-deleting" | "subject-registered" }
  | { kind: "error"; error: ApiError };

export interface SignInContext {
  provider: AuthProvider;
  contact: PendingContact;
  next?: string;
  deps?: SessionDeps;
}

function fromOutcome(
  outcome: ExchangeOutcome,
  pending: Omit<PendingSignIn, "signUp">,
  signUp?: PendingSignUp,
): SignInStep {
  switch (outcome.kind) {
    case "signed-in":
      return { kind: "session", claims: outcome.claims };
    case "needs-sign-up":
      return { kind: "sign-up", pending: { ...pending } };
    case "needs-mfa":
      return {
        kind: "mfa",
        pending: signUp === undefined ? { ...pending } : { ...pending, signUp },
      };
    case "user-disabled":
      return { kind: "refused", reason: "user-disabled" };
    case "tenant-deleting":
      return { kind: "refused", reason: "tenant-deleting" };
    case "subject-registered":
      return { kind: "refused", reason: "subject-registered" };
    case "provider-unavailable":
    case "failed":
      return { kind: "error", error: outcome.error };
  }
}

function pendingFor(ctx: SignInContext, session: ProviderSession): Omit<PendingSignIn, "signUp"> {
  const pending: Omit<PendingSignIn, "signUp"> = {
    provider: ctx.provider.name,
    session,
    contact: ctx.contact,
  };
  if (ctx.next !== undefined) pending.next = ctx.next;
  return pending;
}

/** A verified provider session: the session, or the step that still stands between. */
export async function signInWithProviderSession(
  ctx: SignInContext,
  session: ProviderSession,
): Promise<SignInStep> {
  const outcome = await exchangeSession(session, ctx.provider.name, ctx.deps);
  return fromOutcome(outcome, pendingFor(ctx, session));
}

/** The sign-up form's submit for a pending sign-in: the new tenant's session, or the MFA step. */
export async function completeSignUp(
  ctx: SignInContext,
  pending: PendingSignIn,
  input: SignUpInput,
): Promise<SignInStep> {
  const outcome = await signUpTenant(pending.session, ctx.provider.name, input, ctx.deps);
  return fromOutcome(outcome, pendingFor(ctx, pending.session), {
    kind: input.kind,
    name: input.name,
    displayName: input.displayName,
  });
}

/**
 * The second factor verified at the provider (aal2): exchange again, or finish the sign-up
 * the pending cookie kept, so the session carries `mfa: true`.
 */
export async function completeMfa(
  ctx: SignInContext,
  pending: PendingSignIn,
  verified: ProviderSession,
): Promise<SignInStep> {
  if (pending.signUp !== undefined) {
    const outcome = await signUpTenant(verified, ctx.provider.name, pending.signUp, ctx.deps);
    return fromOutcome(outcome, pendingFor(ctx, verified), pending.signUp);
  }
  const outcome = await exchangeSession(verified, ctx.provider.name, ctx.deps);
  return fromOutcome(outcome, pendingFor(ctx, verified));
}

/** Seconds since the epoch of `now`. */
function at(deps: SessionDeps | undefined): number {
  return epochSeconds(deps?.now ?? new Date());
}

/** Whether the identity token is within the refresh margin of expiring (or has no expiry). */
export function needsRefresh(claims: SessionClaims, now: number, env: WebEnv): boolean {
  if (claims.cwToken === undefined || claims.cwTokenExpiresAt === undefined) return false;
  return claims.cwTokenExpiresAt - now < env.CW_WEB_TOKEN_REFRESH_SECONDS;
}

/** Whether /me was last read longer ago than the recheck interval. */
export function needsRecheck(claims: SessionClaims, now: number, env: WebEnv): boolean {
  if (claims.cwToken === undefined) return false;
  return now - (claims.checkedAt ?? 0) >= env.CW_WEB_SESSION_RECHECK_SECONDS;
}

export type UpkeepOutcome =
  /** Nothing to do: the claims stand as they are. */
  | { kind: "unchanged" }
  /** New claims to write back (a fresh token, or what /me said). */
  | { kind: "updated"; claims: SessionClaims }
  /** Identity says the session is gone: clear the cookie and sign the person out. */
  | { kind: "revoked" }
  /** Identity could not be reached or reads no token: keep the claims, try again later. */
  | { kind: "deferred"; claims: SessionClaims; error: ApiError };

/**
 * A refresh through the provider and a new exchange: the same person, a fresh identity token.
 * The session's own window (`issuedAt`, `expiresAt`) is kept: a refresh never extends it.
 */
export async function refreshSession(
  provider: AuthProvider,
  claims: SessionClaims,
  deps: SessionDeps = {},
): Promise<Result<SessionClaims, ApiError>> {
  if (claims.providerRefreshToken === undefined) {
    return err(noRefresh("The session carries no refresh token; sign in again."));
  }
  const refreshed = await provider.refresh(claims.providerRefreshToken);
  if (!refreshed.ok) return refreshed;
  const outcome = await exchangeSession(refreshed.value, provider.name, deps);
  if (outcome.kind !== "signed-in") {
    return err(
      outcome.kind === "failed" || outcome.kind === "provider-unavailable"
        ? outcome.error
        : noRefresh(`The identity service answered ${outcome.kind} to the refresh.`),
    );
  }
  return ok({
    ...outcome.claims,
    issuedAt: claims.issuedAt,
    expiresAt: claims.expiresAt,
    ...(claims.analyticsConsent === undefined ? {} : { analyticsConsent: claims.analyticsConsent }),
  });
}

function noRefresh(detail: string): ApiError {
  return {
    kind: "unauthenticated",
    status: 401,
    requestId: "",
    message: "The session could not be refreshed",
    problem: {
      type: "urn:compliancewatch:problem:web-session-refresh-failed",
      title: "The session could not be refreshed",
      status: 401,
      detail,
    },
  };
}

/**
 * What the proxy does for a session on its way through: refresh the token when it is about to
 * expire, re-read /me when the last read is old, and sign the person out when identity says the
 * session is revoked (a bumped session version, a disabled user, a tenant being deleted). A
 * refresh that fails because identity refused the person is a revocation too; one that fails
 * because nothing answered is deferred.
 */
export async function keepSessionCurrent(
  provider: AuthProvider,
  claims: SessionClaims,
  deps: SessionDeps = {},
): Promise<UpkeepOutcome> {
  const env = deps.env ?? getEnv();
  const now = at(deps);
  let current = claims;
  let changed = false;
  if (needsRefresh(current, now, env)) {
    const refreshed = await refreshSession(provider, current, deps);
    if (!refreshed.ok) {
      const { error } = refreshed;
      if (error.kind === "network" || error.kind === "unavailable" || error.kind === "server") {
        return { kind: "deferred", claims: current, error };
      }
      return { kind: "revoked" };
    }
    current = refreshed.value;
    changed = true;
  }
  if (needsRecheck(current, now, env)) {
    const read = await readMe(current, deps);
    switch (read.kind) {
      case "ok":
        current = claimsFromMe(current, read.me, deps.now ?? new Date());
        changed = true;
        break;
      case "revoked":
        return { kind: "revoked" };
      case "unverifiable":
      case "failed": {
        // Nothing to learn now: note the attempt so the next request does not ask again at once.
        const deferred = { ...current, checkedAt: now };
        return { kind: "deferred", claims: deferred, error: read.error };
      }
    }
  }
  return changed ? { kind: "updated", claims: current } : { kind: "unchanged" };
}

import "server-only";

import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { toSessionDto } from "@/entities/session/mappers";
import type { SessionClaims, SessionDto } from "@/entities/session/types";
import { forbiddenHref, signInHref } from "@/shared/config/nav";
import { hasRole, isRegulatory } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { hrefFor } from "@/shared/config/screens";
import type { Screen } from "@/shared/config/screens";
import { decryptSession, readSessionCookie } from "./session";

/**
 * The data access layer's gates: the authoritative checks every page, layout, server action
 * and route handler runs. The proxy only checks that a cookie exists; here the cookie is
 * decrypted and the roles are compared with what the screen or action needs.
 *
 *   verifySession()        the claims, or null; memoised per request with React's cache
 *   requireSession()       claims, or a redirect to /sign-in?next=
 *   requireRole(roles)     claims holding one of the roles, or /sign-in (anonymous) or
 *                          /forbidden (wrong role); "public" returns the optional session
 *   requireScreen(screen)  requireRole with the entry's roles and tenant kinds; an admin
 *                          entry goes through requireAdmin and answers 404 to a regulatory
 *                          role the entry does not list; requireScreenSession is the same
 *                          for an entry that is never public
 *   requireAdmin()         a regulatory role, or notFound(): a tenant role must not learn
 *                          that a tool exists
 *   sessionForRender()     the render-safe view for shells and pages, never the token
 *
 * A page calls its gate on the first line and re-checks nothing else; a server action calls
 * the same gate again, because the proxy is not on its path (Next runs server functions as
 * POSTs to the page's route). This module never writes a cookie: rotation and refresh belong
 * to the proxy and to actions.
 */
async function readSession(): Promise<SessionClaims | null> {
  const token = await readSessionCookie();
  return token === undefined ? null : decryptSession(token);
}

/** The session of the current request, decrypted once per request. */
export const verifySession: () => Promise<SessionClaims | null> = cache(readSession);

export interface GateOptions {
  /** Where to return after signing in; only a same-origin path is honoured. */
  next?: string;
}

export async function requireSession(options: GateOptions = {}): Promise<SessionClaims> {
  const session = await verifySession();
  if (session === null) redirect(signInHref(options.next));
  return session;
}

export async function requireRole(
  roles: readonly Role[],
  options?: GateOptions,
): Promise<SessionClaims>;
export async function requireRole(
  roles: readonly Role[] | "public",
  options?: GateOptions,
): Promise<SessionClaims | null>;
export async function requireRole(
  roles: readonly Role[] | "public",
  options: GateOptions = {},
): Promise<SessionClaims | null> {
  if (roles === "public") return verifySession();
  const session = await requireSession(options);
  if (!hasRole(session, roles)) redirect(forbiddenHref());
  return session;
}

export async function requireTenantKind(
  kinds: readonly TenantKind[],
  options: GateOptions = {},
): Promise<SessionClaims> {
  const session = await requireSession(options);
  if (!kinds.includes(session.tenantKind)) redirect(forbiddenHref());
  return session;
}

/** The regulatory roles only; anyone else sees a 404, as if the tool did not exist. */
export async function requireAdmin(options: GateOptions = {}): Promise<SessionClaims> {
  const session = await requireSession(options);
  if (!isRegulatory(session)) notFound();
  return session;
}

/** The gate a registry entry asks for: its roles and tenant kinds, or the admin gate. */
export async function requireScreen(
  screen: Screen,
  params: Readonly<Record<string, string>> = {},
): Promise<SessionClaims | null> {
  if (screen.section === "admin") {
    // An admin tool narrower than the regulatory set (admin only) is a 404 to the others too.
    const session = await requireAdmin({ next: hrefFor(screen, params) });
    if (screen.roles !== "public" && !hasRole(session, screen.roles)) notFound();
    return session;
  }
  const session = await requireRole(screen.roles, { next: hrefFor(screen, params) });
  if (
    session !== null &&
    screen.tenantKinds !== undefined &&
    !screen.tenantKinds.includes(session.tenantKind)
  ) {
    redirect(forbiddenHref());
  }
  return session;
}

/** requireScreen for an entry that is never public; a public entry here is a programming error. */
export async function requireScreenSession(
  screen: Screen,
  params: Readonly<Record<string, string>> = {},
): Promise<SessionClaims> {
  if (screen.roles === "public") throw new Error(`${screen.id} is public; use requireScreen`);
  const session = await requireScreen(screen, params);
  if (session === null) redirect(signInHref(hrefFor(screen, params)));
  return session;
}

/** What a shell or a page may pass to components: the session facts without tokens. */
export async function sessionForRender(): Promise<SessionDto | null> {
  const session = await verifySession();
  return session === null ? null : toSessionDto(session);
}

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/entities/session/types";
import { signInHref } from "@/shared/config/nav";
import { matchScreen } from "@/shared/config/screens";

/**
 * The optimistic check that runs before a route renders (Node runtime): a request for a
 * role-gated screen or for anything under /admin without a `cw_session` cookie is sent to
 * /sign-in with the path to return to. The cookie is not decrypted here; the data access layer
 * (server/dal.ts) is the authoritative gate on every page and action, and it handles a cookie
 * that is present but expired, tampered or short of the role. Public screens, handlers and
 * unknown paths pass through: the page or the 404 answers them.
 *
 * Session rotation, the identity re-read and the /admin allow-list arrive with the real
 * sign-in and run here too, because a cookie may be written on the way through the proxy but
 * never during a render.
 */
export const config = {
  // Everything except Next's own assets, route handlers under /api and /api-bff, and files with an
  // extension. The /api-bff handlers check the session themselves, and a request the proxy runs
  // on has its body buffered (up to 10 MB, cut silently past it) so the proxy could read it: an
  // upload streamed through /api-bff must not pass here.
  matcher: ["/((?!_next/static|_next/image|api/|api-bff/|.*\\..*).*)"],
};

export type ProxyDecision = { kind: "pass" } | { kind: "sign-in"; next: string };

const ADMIN_PREFIX = "/admin";

function isAdminPath(pathname: string): boolean {
  return pathname === ADMIN_PREFIX || pathname.startsWith(`${ADMIN_PREFIX}/`);
}

/** Pure: what the proxy does for a pathname given whether a session cookie is present. */
export function decide(pathname: string, search: string, hasSessionCookie: boolean): ProxyDecision {
  const needsSession = isAdminPath(pathname) || needsSessionForScreen(pathname);
  if (!needsSession || hasSessionCookie) return { kind: "pass" };
  return { kind: "sign-in", next: `${pathname}${search}` };
}

function needsSessionForScreen(pathname: string): boolean {
  const match = matchScreen(pathname);
  return match !== null && match.screen.roles !== "public";
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const decision = decide(pathname, search, request.cookies.has(SESSION_COOKIE_NAME));
  if (decision.kind === "sign-in") {
    return NextResponse.redirect(new URL(signInHref(decision.next), request.url));
  }
  return NextResponse.next();
}

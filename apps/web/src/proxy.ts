import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/entities/session/types";
import { PENDING_COOKIE_NAME } from "@/server/auth/pending";
import { providerFor } from "@/server/auth/provider";
import { keepSessionCurrent } from "@/server/auth/usecases";
import { getEnv, type WebEnvName } from "@/server/env";
import { decryptSession, encryptSession, sessionCookieOptions } from "@/server/session";
import { SIGNED_OUT_REASON, forbiddenHref, signInHref, signedOutHref } from "@/shared/config/nav";
import { hrefFor, matchScreen, screenById } from "@/shared/config/screens";
import { clientIpOf, ipInAllowList, parseAllowList } from "@/shared/lib/cidr";

/**
 * What runs before a route renders (Node runtime), on every page request but Next's assets,
 * the route handlers under /api and /api-bff, and files:
 *
 * 1. The optimistic session check: a request for a role-gated screen or for anything under
 *    /admin without a `cw_session` cookie goes to /sign-in with the path to return to. The
 *    data access layer (server/dal.ts) is the authoritative gate on every page and action; it
 *    handles a cookie that is present but expired, tampered or short of the role.
 * 2. The /admin allow-list (CW_WEB_ADMIN_IP_ALLOWLIST, shared/lib/cidr.ts): the client address
 *    from the proxy headers only when CW_WEB_TRUST_FORWARDED_IP says so, else none. An empty
 *    list opens /admin to every address in local, test and staging (one warning at startup,
 *    src/instrumentation.ts) and to none in prod, where /admin is then a 404 as if the tools did
 *    not exist. An address outside the list sees /forbidden. The role check stays the cookie's
 *    and the gates'; no network call decides it here.
 * 3. Session upkeep (server/auth/usecases.ts): a cookie is decrypted here, the identity token
 *    refreshed through the provider when it is about to expire, and /me re-read once the last
 *    read is old; the new cookie goes on the response and into the request the render sees. A
 *    revoked session is cleared and sent to /sign-in?reason=signed-out, which is also where a
 *    render that met a revoked token sends the person (server/auth/signed-out.ts): a render
 *    cannot clear a cookie, so the proxy clears it on that path. These are the only requests
 *    on which the proxy calls a service.
 * 4. A Content-Security-Policy with a nonce for this request's scripts (base64 of a random
 *    UUID, `x-nonce` on the forwarded request so Next applies it to its own scripts); nosniff,
 *    X-Frame-Options, Referrer-Policy and Permissions-Policy stay in next.config.ts, since
 *    they need no nonce.
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

/** A path no page serves: the catch-all answers it with the 404 page and no admin markup. */
export const ADMIN_NOT_FOUND_PATH = "/__admin-not-found__";

export const NONCE_HEADER = "x-nonce";
export const CSP_HEADER = "content-security-policy";

export function isAdminPath(pathname: string): boolean {
  return pathname === ADMIN_PREFIX || pathname.startsWith(`${ADMIN_PREFIX}/`);
}

/**
 * Pure: what the proxy does for a pathname given which cookies are present. A pending sign-in
 * (cw_pending) opens the two-step verification page alone: a person whose roles need the factor
 * verifies it there before identity issues the session.
 */
export function decide(
  pathname: string,
  search: string,
  hasSessionCookie: boolean,
  hasPendingCookie = false,
): ProxyDecision {
  const needsSession = isAdminPath(pathname) || needsSessionForScreen(pathname);
  if (!needsSession || hasSessionCookie) return { kind: "pass" };
  if (hasPendingCookie && pathname === hrefFor(screenById("account.mfa"))) return { kind: "pass" };
  return { kind: "sign-in", next: `${pathname}${search}` };
}

function needsSessionForScreen(pathname: string): boolean {
  const match = matchScreen(pathname);
  return match !== null && match.screen.roles !== "public";
}

export type AdminGate = "allowed" | "forbidden" | "not-found";

/** Pure: the allow-list's answer for a client address, the configured list and the environment. */
export function adminGate(
  ip: string | null,
  allowList: readonly string[],
  env: WebEnvName,
): AdminGate {
  const { ranges } = parseAllowList(allowList);
  if (ranges.length === 0) return env === "prod" ? "not-found" : "allowed";
  return ipInAllowList(ip, ranges) ? "allowed" : "forbidden";
}

export function makeNonce(): string {
  return Buffer.from(crypto.randomUUID()).toString("base64");
}

export interface CspOptions {
  /** `next dev`: React rebuilds server stacks with eval and HMR talks over a web socket. */
  dev: boolean;
  /** Outside local: ask the browser to upgrade any http subresource. */
  secure: boolean;
}

/** The policy for one request: scripts need this request's nonce; styles may be inline. */
export function contentSecurityPolicy(nonce: string, options: CspOptions): string {
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${options.dev ? " 'unsafe-eval'" : ""}`,
    // Tailwind's generated stylesheet is a file; Radix and Next set element styles inline.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src 'self'${options.dev ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  if (options.secure) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}

/** The request's cookie header with one cookie replaced or added. */
export function cookieHeaderWith(request: NextRequest, name: string, value: string): string {
  const pairs = request.cookies
    .getAll()
    .filter((cookie) => cookie.name !== name)
    .map((cookie) => `${cookie.name}=${cookie.value}`);
  pairs.push(`${name}=${value}`);
  return pairs.join("; ");
}

/** The request's cookie header without one cookie ("" when none is left). */
export function cookieHeaderWithout(request: NextRequest, name: string): string {
  return request.cookies
    .getAll()
    .filter((cookie) => cookie.name !== name)
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
}

function logLine(event: string, fields: Record<string, unknown>): void {
  console.info(JSON.stringify({ level: "info", event, ...fields }));
}

/**
 * A redirect the browser follows with a GET: 303 for anything posted (a server action, the
 * sign-out form), since a 307 would replay the body at the sign-in page; 307 for a page request.
 */
export function redirectStatus(method: string): 303 | 307 {
  return method === "GET" || method === "HEAD" ? 307 : 303;
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const env = getEnv();
  const { pathname, search } = request.nextUrl;
  const cookie = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const hasCookie = cookie !== undefined && cookie !== "";
  const nonce = makeNonce();
  const csp = contentSecurityPolicy(nonce, {
    dev: process.env.NODE_ENV === "development",
    secure: env.CW_WEB_ENV !== "local" && env.CW_WEB_ENV !== "test",
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(NONCE_HEADER, nonce);
  requestHeaders.set(CSP_HEADER, csp);
  const secured = (response: NextResponse): NextResponse => {
    response.headers.set(CSP_HEADER, csp);
    return response;
  };
  const expired = { ...sessionCookieOptions(env), maxAge: 0 };
  const signInPath = hrefFor(screenById("system.sign-in"));

  // A session that ended somewhere in a render: the cookie goes on the way to the sign-in page.
  if (
    pathname === signInPath &&
    request.nextUrl.searchParams.get("reason") === SIGNED_OUT_REASON &&
    hasCookie
  ) {
    requestHeaders.set("cookie", cookieHeaderWithout(request, SESSION_COOKIE_NAME));
    const response = NextResponse.next({ request: { headers: requestHeaders } });
    response.cookies.set(SESSION_COOKIE_NAME, "", expired);
    logLine("session_cleared", { reason: SIGNED_OUT_REASON });
    return secured(response);
  }

  const pendingCookie = request.cookies.get(PENDING_COOKIE_NAME)?.value;
  const hasPending = pendingCookie !== undefined && pendingCookie !== "";
  const decision = decide(pathname, search, hasCookie, hasPending);
  if (decision.kind === "sign-in") {
    return secured(
      NextResponse.redirect(
        new URL(signInHref(decision.next), request.url),
        redirectStatus(request.method),
      ),
    );
  }

  if (isAdminPath(pathname)) {
    const ip = clientIpOf(request.headers, { trustForwardedIp: env.CW_WEB_TRUST_FORWARDED_IP });
    const gate = adminGate(ip, env.CW_WEB_ADMIN_IP_ALLOWLIST, env.CW_WEB_ENV);
    if (gate !== "allowed") {
      logLine("admin_allowlist_refused", { gate, ip, path: pathname });
      const target = gate === "forbidden" ? forbiddenHref() : ADMIN_NOT_FOUND_PATH;
      return secured(
        NextResponse.rewrite(new URL(target, request.url), {
          request: { headers: requestHeaders },
        }),
      );
    }
  }

  if (hasCookie) {
    const claims = await decryptSession(cookie);
    if (claims !== null && claims.cwToken !== undefined) {
      const provider = providerFor(env);
      if (provider.ok) {
        const outcome = await keepSessionCurrent(provider.value, claims, { env });
        if (outcome.kind === "revoked") {
          logLine("session_revoked", { user_id: claims.userId, path: pathname });
          const response = NextResponse.redirect(
            new URL(signedOutHref(), request.url),
            redirectStatus(request.method),
          );
          response.cookies.set(SESSION_COOKIE_NAME, "", expired);
          return secured(response);
        }
        if (outcome.kind === "updated" || outcome.kind === "deferred") {
          if (outcome.kind === "deferred") {
            logLine("session_upkeep_deferred", {
              user_id: claims.userId,
              reason: outcome.error.problem?.type ?? outcome.error.kind,
            });
          }
          const token = await encryptSession(outcome.claims);
          requestHeaders.set("cookie", cookieHeaderWith(request, SESSION_COOKIE_NAME, token));
          const response = NextResponse.next({ request: { headers: requestHeaders } });
          response.cookies.set(SESSION_COOKIE_NAME, token, sessionCookieOptions(env));
          return secured(response);
        }
      }
    }
  }

  return secured(NextResponse.next({ request: { headers: requestHeaders } }));
}

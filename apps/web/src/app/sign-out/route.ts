import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/entities/session/types";
import { PENDING_COOKIE_NAME, pendingCookieOptions } from "@/server/auth/pending";
import { providerFor } from "@/server/auth/provider";
import { getEnv } from "@/server/env";
import { isSameOriginRequest } from "@/server/origin";
import { RECIPIENT_COOKIE_NAME, recipientCookieOptions } from "@/server/remembered-recipients";
import { decryptSession, sessionCookieOptions } from "@/server/session";
import { signInHref } from "@/shared/config/nav";

/**
 * Sign out: ends the session at the provider when it keeps one (Supabase's refresh token is
 * revoked; the fake adapter keeps none), then expires the session cookie, a pending sign-in,
 * and the notification recipients this device remembered for the settings pages, and sends
 * the browser to the sign-in page. POST only (the shells submit a plain form, so it works
 * without JavaScript); Next answers 405 to any other method. A request from another site is
 * refused (server/origin.ts), so a foreign page cannot sign a visitor out. The redirect is
 * relative, so the browser stays on the host it used: Next builds `request.nextUrl` from the
 * server's bind address, not from that host.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const env = getEnv();
  const trustForwardedHost = env.CW_WEB_TRUST_FORWARDED_IP;
  if (!isSameOriginRequest(request.headers, { trustForwardedHost })) {
    return NextResponse.json(
      {
        type: "urn:compliancewatch:problem:web-cross-origin-request",
        title: "Cross-origin sign-out refused",
        status: 403,
      },
      { status: 403, headers: { "content-type": "application/problem+json" } },
    );
  }
  const cookie = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (cookie !== undefined && cookie !== "") {
    const claims = await decryptSession(cookie);
    const provider = providerFor(env);
    if (claims?.providerRefreshToken !== undefined && provider.ok) {
      await provider.value.signOut(claims.providerRefreshToken);
    }
  }
  const response = new NextResponse(null, { status: 303, headers: { location: signInHref() } });
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...sessionCookieOptions(env), maxAge: 0 });
  response.cookies.set(PENDING_COOKIE_NAME, "", { ...pendingCookieOptions(env), maxAge: 0 });
  response.cookies.set(RECIPIENT_COOKIE_NAME, "", { ...recipientCookieOptions(env), maxAge: 0 });
  return response;
}

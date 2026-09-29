import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/entities/session/types";
import { getEnv } from "@/server/env";
import { isSameOriginRequest } from "@/server/origin";
import { RECIPIENT_COOKIE_NAME, recipientCookieOptions } from "@/server/remembered-recipients";
import { sessionCookieOptions } from "@/server/session";
import { signInHref } from "@/shared/config/nav";

/**
 * Sign out: expires the session cookie (and the notification recipients this device remembered
 * for the settings pages) and sends the browser to the sign-in page. POST only
 * (the shells submit a plain form, so it works without JavaScript); Next answers 405 to any
 * other method. A request from another site is refused (server/origin.ts), so a foreign page
 * cannot sign a visitor out. The redirect is relative, so the browser stays on the host it
 * used: Next builds `request.nextUrl` from the server's bind address, not from that host.
 * Nothing is revoked at a provider today; the real sign-in adds that.
 */
export function POST(request: NextRequest): NextResponse {
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
  const response = new NextResponse(null, { status: 303, headers: { location: signInHref() } });
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...sessionCookieOptions(env), maxAge: 0 });
  response.cookies.set(RECIPIENT_COOKIE_NAME, "", { ...recipientCookieOptions(env), maxAge: 0 });
  return response;
}

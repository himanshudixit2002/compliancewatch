import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/entities/session/types";
import { sessionCookieOptions } from "@/server/session";
import { signInHref } from "@/shared/config/nav";

/**
 * Sign out: expires the session cookie and sends the browser to the sign-in page. POST only
 * (the shells submit a plain form, so it works without JavaScript); Next answers 405 to any
 * other method. A request whose Origin is another site is refused, so a foreign page cannot
 * sign a visitor out. Nothing is revoked at a provider today; the real sign-in adds that.
 */
export function POST(request: NextRequest): NextResponse {
  const origin = request.headers.get("origin");
  if (origin !== null && !sameOrigin(origin, request.nextUrl.origin)) {
    return NextResponse.json(
      {
        type: "urn:compliancewatch:problem:web-cross-origin-request",
        title: "Cross-origin sign-out refused",
        status: 403,
      },
      { status: 403, headers: { "content-type": "application/problem+json" } },
    );
  }
  const response = NextResponse.redirect(new URL(signInHref(), request.nextUrl.origin), 303);
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...sessionCookieOptions(), maxAge: 0 });
  return response;
}

function sameOrigin(origin: string, expected: string): boolean {
  try {
    return new URL(origin).origin === expected;
  } catch {
    return false;
  }
}

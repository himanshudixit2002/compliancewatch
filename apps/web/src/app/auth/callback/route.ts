import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { PENDING_COOKIE_NAME, encryptPending, pendingCookieOptions } from "@/server/auth/pending";
import { providerFor } from "@/server/auth/provider";
import { signInWithProviderSession, type SignInContext } from "@/server/auth/usecases";
import { getEnv } from "@/server/env";
import { encryptSession, sessionCookieOptions } from "@/server/session";
import { homeFor, mfaHref, signInHref, signUpHref } from "@/shared/config/nav";
import { safeNext, withQuery } from "@/shared/lib/url";

/**
 * Where the email link comes back: `?token_hash=<hash>&type=magiclink[&next=<path>]`. The
 * handler exchanges the hash with the provider, then runs the same exchange as the code step:
 * a session cookie and a redirect, the sign-up or second-factor step with the pending cookie,
 * or the sign-in page saying the link is not valid any more. GET, since a mail client opens a
 * link; the hash is single-use at the provider and never lands in a page of this app. Every
 * redirect is a relative Location, so the browser stays on the host it used: under `next start`
 * Next builds `request.nextUrl` from the server's bind address, not from that host (as the
 * sign-out handler says).
 */
export const dynamic = "force-dynamic";

/** A 303 to a path of this app, relative on purpose. */
function redirectTo(location: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { location } });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const env = getEnv();
  const tokenHash = request.nextUrl.searchParams.get("token_hash")?.trim() ?? "";
  const next = safeNext(request.nextUrl.searchParams.get("next"), "");
  const expired = () => redirectTo(withQuery(signInHref(), { error: "link-expired", next }));
  if (tokenHash === "") return expired();
  const provider = providerFor(env);
  if (!provider.ok) return redirectTo(signInHref(next || undefined));
  const exchanged = await provider.value.exchangeEmailLink(tokenHash);
  if (!exchanged.ok) return expired();
  const contact = emailOf(exchanged.value.accessToken);
  const ctx: SignInContext = { provider: provider.value, contact };
  if (next !== "") ctx.next = next;
  const step = await signInWithProviderSession(ctx, exchanged.value);
  switch (step.kind) {
    case "session": {
      const response = redirectTo(safeNext(next, homeFor(step.claims)));
      response.cookies.set(PENDING_COOKIE_NAME, "", { ...pendingCookieOptions(env), maxAge: 0 });
      response.cookies.set(
        "cw_session",
        await encryptSession(step.claims),
        sessionCookieOptions(env),
      );
      return response;
    }
    case "sign-up":
    case "mfa": {
      const target = step.kind === "sign-up" ? signUpHref() : mfaHref(next || undefined);
      const response = redirectTo(target);
      response.cookies.set(
        PENDING_COOKIE_NAME,
        await encryptPending(step.pending),
        pendingCookieOptions(env),
      );
      return response;
    }
    case "refused": {
      const error =
        step.reason === "user-disabled"
          ? "disabled"
          : step.reason === "tenant-deleting"
            ? "tenant-deleting"
            : "registered";
      return redirectTo(withQuery(signInHref(), { error }));
    }
    case "error":
      return expired();
  }
}

/** The address a provider token names, when its claims say (the fake and GoTrue both do). */
function emailOf(token: string): { email?: string } {
  const parts = token.split(".");
  if (parts.length !== 3) return {};
  try {
    const claims: unknown = JSON.parse(Buffer.from(parts[1] as string, "base64url").toString());
    const email = (claims as { email?: unknown }).email;
    return typeof email === "string" && email !== "" ? { email } : {};
  } catch {
    return {};
  }
}

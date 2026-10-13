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
 * link; the hash is single-use at the provider and never lands in a page of this app.
 */
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const env = getEnv();
  const tokenHash = request.nextUrl.searchParams.get("token_hash")?.trim() ?? "";
  const next = safeNext(request.nextUrl.searchParams.get("next"), "");
  const expired = () =>
    NextResponse.redirect(
      new URL(withQuery(signInHref(), { error: "link-expired", next }), request.url),
      303,
    );
  if (tokenHash === "") return expired();
  const provider = providerFor(env);
  if (!provider.ok) {
    return NextResponse.redirect(new URL(signInHref(next || undefined), request.url), 303);
  }
  const exchanged = await provider.value.exchangeEmailLink(tokenHash);
  if (!exchanged.ok) return expired();
  const contact = emailOf(exchanged.value.accessToken);
  const ctx: SignInContext = { provider: provider.value, contact };
  if (next !== "") ctx.next = next;
  const step = await signInWithProviderSession(ctx, exchanged.value);
  switch (step.kind) {
    case "session": {
      const response = NextResponse.redirect(
        new URL(safeNext(next, homeFor(step.claims)), request.url),
        303,
      );
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
      const response = NextResponse.redirect(new URL(target, request.url), 303);
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
      return NextResponse.redirect(new URL(withQuery(signInHref(), { error }), request.url), 303);
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

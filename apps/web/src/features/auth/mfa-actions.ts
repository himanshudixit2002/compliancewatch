"use server";

import { redirect } from "next/navigation";
import { epochSeconds } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { readPending } from "@/server/auth/pending";
import type { PendingSignIn } from "@/server/auth/pending";
import { providerFor } from "@/server/auth/provider";
import type { AuthProvider, ProviderSession, TotpEnrolment } from "@/server/auth/provider";
import { providerSessionOf, withProviderSession } from "@/server/auth/sessions";
import { completeMfa, signInWithProviderSession, type SignInContext } from "@/server/auth/usecases";
import { verifySession } from "@/server/dal";
import { getEnv } from "@/server/env";
import { err, toActionState, webError } from "@/server/result";
import { setSessionCookie } from "@/server/session";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { safeNext } from "@/shared/lib/url";
import { finishSignIn } from "./flow";
import { parseMfaForm } from "./model/sign-in";

/**
 * The two-step verification page's actions, for a person with a session (who verifies,
 * enrols or removes a factor) or with a pending sign-in (whose roles need the second factor
 * before identity issues a session). After a verification identity is asked again, so the
 * session carries `mfa: true`: a pending sign-in completes (the exchange, or the sign-up the
 * pending cookie kept) and a signed-in person gets a fresh cookie. A signed-in person acts with
 * the provider session the cookie carries; when its access token is about to expire the action
 * refreshes it and writes the rotated pair back at once, and a factor verify, which rotates
 * the pair too, is written back before anything else runs: GoTrue spends a refresh token on
 * use, so a pair that misses the cookie ends the session at the next refresh.
 */
export interface MfaView {
  enrolment?: TotpEnrolment;
  verified?: boolean;
  removed?: boolean;
}

interface MfaContext {
  provider: AuthProvider;
  session: ProviderSession;
  pending: PendingSignIn | null;
  /** The signed-in person's claims, which take the provider pair whenever it rotates. */
  claims: SessionClaims | null;
  next?: string;
}

type Resolved = { ok: true; ctx: MfaContext } | { ok: false; state: ActionState<MfaView> };

/** Who is verifying: the pending sign-in, else the signed-in person's provider session. */
async function resolve(next: string | undefined): Promise<Resolved> {
  const provider = providerFor(getEnv());
  if (!provider.ok) return { ok: false, state: toActionState<MfaView>(err(provider.error)) };
  const pending = await readPending();
  if (pending !== null) {
    const ctx: MfaContext = {
      provider: provider.value,
      session: pending.session,
      pending,
      claims: null,
    };
    const wanted = next ?? pending.next;
    if (wanted !== undefined) ctx.next = wanted;
    return { ok: true, ctx };
  }
  const claims = await verifySession();
  if (claims === null || claims.providerRefreshToken === undefined) {
    return {
      ok: false,
      state: toActionState<MfaView>(
        err(webError("unauthenticated", "web-mfa-no-session", t("mfa.error.noSession"))),
      ),
    };
  }
  const current = providerSessionOf(claims, epochSeconds(new Date()));
  if (current !== null) {
    const ready: MfaContext = { provider: provider.value, session: current, pending: null, claims };
    if (next !== undefined) ready.next = next;
    return { ok: true, ctx: ready };
  }
  // The cookie's provider token is stale (the proxy's upkeep was deferred, or the cookie is
  // older than this field): refresh, and write the rotated pair back whatever the action answers.
  const refreshed = await provider.value.refresh(claims.providerRefreshToken);
  if (!refreshed.ok) return { ok: false, state: toActionState<MfaView>(err(refreshed.error)) };
  const rotated = withProviderSession(claims, refreshed.value);
  await setSessionCookie(rotated);
  const fresh: MfaContext = {
    provider: provider.value,
    session: refreshed.value,
    pending: null,
    claims: rotated,
  };
  if (next !== undefined) fresh.next = next;
  return { ok: true, ctx: fresh };
}

function signInContext(ctx: MfaContext): SignInContext {
  const context: SignInContext = {
    provider: ctx.provider,
    contact: ctx.pending?.contact ?? {},
  };
  if (ctx.next !== undefined) context.next = ctx.next;
  return context;
}

/** The verified (aal2) provider session becomes the session: pending completes, signed-in refreshes. */
async function settle(ctx: MfaContext, verified: ProviderSession): Promise<ActionState<MfaView>> {
  // The verify rotated the pair: a signed-in person's cookie takes it before the exchange, so
  // an identity that does not answer leaves a session that still refreshes.
  if (ctx.claims !== null) await setSessionCookie(withProviderSession(ctx.claims, verified));
  const context = signInContext(ctx);
  const step =
    ctx.pending === null
      ? await signInWithProviderSession(context, verified)
      : await completeMfa(context, ctx.pending, verified);
  // A pending sign-in lands where any sign-in lands; a signed-in person returns to `next` or
  // to the account page, where the factor now shows as verified.
  const fallback = ctx.pending === null ? hrefFor(screenById("account.home")) : undefined;
  const next = safeNext(ctx.next, fallback ?? "");
  return finishSignIn<MfaView>(step, {
    ...(next === "" ? {} : { next }),
    newTenant: ctx.pending?.signUp !== undefined,
  });
}

/**
 * Verify the second factor: the confirm step of the fake adapter (no code), or an
 * authenticator app's code against a fresh challenge for the factor named (the one just
 * enrolled, or the first verified one).
 */
export async function verifySecondFactor(
  _state: ActionState<MfaView>,
  formData: FormData,
): Promise<ActionState<MfaView>> {
  const configured = providerFor(getEnv());
  const needsCode = configured.ok && configured.value.mfaMode === "totp";
  const parsed = parseMfaForm(formData, { code: needsCode });
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const resolved = await resolve(parsed.value.next);
  if (!resolved.ok) return resolved.state;
  const { ctx } = resolved;
  let factorId = parsed.value.factorId;
  if (factorId === undefined) {
    const factors = await ctx.provider.mfa.listFactors(ctx.session);
    if (!factors.ok) return toActionState<MfaView>(err(factors.error));
    factorId =
      factors.value.find((factor) => factor.status === "verified")?.id ?? factors.value[0]?.id;
  }
  if (factorId === undefined && ctx.provider.mfaMode === "totp") {
    return actionFailure(t("mfa.error.noFactor"));
  }
  const challenge = await ctx.provider.mfa.challenge(ctx.session, factorId ?? "");
  if (!challenge.ok) return toActionState<MfaView>(err(challenge.error));
  const verified = await ctx.provider.mfa.verify(
    ctx.session,
    factorId ?? "",
    challenge.value.challengeId,
    parsed.value.code,
  );
  if (!verified.ok) return toActionState<MfaView>(err(verified.error));
  return settle(ctx, verified.value);
}

/** Start enrolling an authenticator app: the QR code and the secret to show. */
export async function enrolAuthenticator(
  _state: ActionState<MfaView>,
  formData: FormData,
): Promise<ActionState<MfaView>> {
  const parsed = parseMfaForm(formData, { code: false });
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const resolved = await resolve(parsed.value.next);
  if (!resolved.ok) return resolved.state;
  const { ctx } = resolved;
  const enrolment = await ctx.provider.mfa.enrolTotp(
    ctx.session,
    parsed.value.friendlyName ?? t("mfa.defaultFactorName"),
  );
  if (!enrolment.ok) return toActionState<MfaView>(err(enrolment.error));
  return { status: "ok", value: { enrolment: enrolment.value } };
}

/** Remove a factor, after a fresh challenge the person answers with a code. */
export async function removeAuthenticator(
  _state: ActionState<MfaView>,
  formData: FormData,
): Promise<ActionState<MfaView>> {
  const parsed = parseMfaForm(formData, { code: true });
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  if (parsed.value.factorId === undefined) return actionFailure(t("mfa.error.noFactor"));
  const resolved = await resolve(parsed.value.next);
  if (!resolved.ok) return resolved.state;
  const { ctx } = resolved;
  if (ctx.pending !== null) {
    return actionFailure(t("mfa.error.signInFirst"));
  }
  const challenge = await ctx.provider.mfa.challenge(ctx.session, parsed.value.factorId);
  if (!challenge.ok) return toActionState<MfaView>(err(challenge.error));
  const verified = await ctx.provider.mfa.verify(
    ctx.session,
    parsed.value.factorId,
    challenge.value.challengeId,
    parsed.value.code,
  );
  if (!verified.ok) return toActionState<MfaView>(err(verified.error));
  if (ctx.claims !== null) await setSessionCookie(withProviderSession(ctx.claims, verified.value));
  const removed = await ctx.provider.mfa.remove(verified.value, parsed.value.factorId);
  if (!removed.ok) return toActionState<MfaView>(err(removed.error));
  redirect(hrefFor(screenById("account.mfa")));
}

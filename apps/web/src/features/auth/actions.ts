"use server";

import { redirect } from "next/navigation";
import { readPending, setPendingCookie } from "@/server/auth/pending";
import { providerFor } from "@/server/auth/provider";
import type { DevPersonaInput } from "@/server/auth/provider";
import {
  completeSignUp,
  signInWithProviderSession,
  type SignInContext,
} from "@/server/auth/usecases";
import { getEnv } from "@/server/env";
import { err, toActionState } from "@/server/result";
import { signInHref } from "@/shared/config/nav";
import type { Role, TenantKind } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { finishSignIn } from "./flow";
import {
  parseCodeForm,
  parseEmailForm,
  parseFakeSignInForm,
  parsePhoneForm,
  parseSignUpForm,
} from "./model/sign-in";
import { callbackUrl } from "./queries";

/**
 * The sign-in forms' server actions. Each checks the form's shape, asks the configured
 * provider to prove who the person is, hands the provider session to the exchange
 * (server/auth/usecases.ts) and ends as `finishSignIn` says: the cookie and a redirect, the
 * sign-up or second-factor step, or the state the form shows. Nothing here trusts a field
 * beyond its shape: identity decides who the person is and what they may hold.
 */

/** What the phone and email forms keep between submits: the step they are on. */
export interface SignInView {
  step: "phone" | "code" | "email";
  phone?: string;
}

/** The development sign-in: a persona identity makes, then the same exchange as anyone's. */
export async function signIn(_state: ActionState, formData: FormData): Promise<ActionState> {
  const parsed = parseFakeSignInForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const provider = providerFor(getEnv());
  if (!provider.ok) return toActionState<undefined>(err(provider.error));
  if (provider.value.signInAsPersona === undefined) {
    return toActionState<undefined>(
      err({
        kind: "bad_request",
        status: 400,
        requestId: "",
        message: "The configured provider has no development sign-in",
      }),
    );
  }
  const { tenantKind, roles, displayName, tenantId, next } = parsed.value;
  const input: DevPersonaInput = {
    // The adapter validates the kind and the roles by value; the casts only name the type.
    tenantKind: tenantKind as TenantKind,
    roles: roles as readonly Role[],
    displayName,
    ...(tenantId === undefined ? {} : { tenantId }),
  };
  const session = await provider.value.signInAsPersona(input);
  if (!session.ok) return toActionState<undefined>(err(session.error));
  const ctx: SignInContext = { provider: provider.value, contact: {} };
  if (next !== undefined) ctx.next = next;
  return finishSignIn(await signInWithProviderSession(ctx, session.value), { next });
}

/** The phone step: ask the provider for a code; the form moves to the code step. */
export async function startPhoneSignIn(
  _state: ActionState<SignInView>,
  formData: FormData,
): Promise<ActionState<SignInView>> {
  const parsed = parsePhoneForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const provider = providerFor(getEnv());
  if (!provider.ok) return toActionState<SignInView>(err(provider.error));
  const started = await provider.value.startPhoneOtp(parsed.value.phone);
  if (!started.ok) return toActionState<SignInView>(err(started.error));
  return { status: "ok", value: { step: "code", phone: parsed.value.phone } };
}

/** The code step: verify it, then exchange the provider session with identity. */
export async function verifyPhoneCode(
  _state: ActionState<SignInView>,
  formData: FormData,
): Promise<ActionState<SignInView>> {
  const parsed = parseCodeForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const provider = providerFor(getEnv());
  if (!provider.ok) return toActionState<SignInView>(err(provider.error));
  const { phone, code, next } = parsed.value;
  const verified = await provider.value.verifyPhoneOtp(phone, code);
  if (!verified.ok) return toActionState<SignInView>(err(verified.error));
  const ctx: SignInContext = { provider: provider.value, contact: { phone } };
  if (next !== undefined) ctx.next = next;
  return finishSignIn(await signInWithProviderSession(ctx, verified.value), { next });
}

/**
 * The email step: ask the provider to send the link, which comes back to /auth/callback. The
 * fake adapter sends nothing and hands the link back: it is kept in cw_pending for the
 * email-sent page to show, so no token reaches a URL the server did not just make.
 */
export async function sendEmailLink(
  _state: ActionState<SignInView>,
  formData: FormData,
): Promise<ActionState<SignInView>> {
  const parsed = parseEmailForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const provider = providerFor(getEnv());
  if (!provider.ok) return toActionState<SignInView>(err(provider.error));
  const { email, next } = parsed.value;
  const sent = await provider.value.sendEmailLink(email, await callbackUrl(next));
  if (!sent.ok) return toActionState<SignInView>(err(sent.error));
  if (sent.value.devLink !== undefined) {
    const link = new URL(sent.value.devLink);
    const token = link.searchParams.get("token_hash") ?? "";
    await setPendingCookie({
      provider: provider.value.name,
      contact: { email },
      session: { accessToken: token, refreshToken: token, expiresAt: 0, aal: "aal1", subject: "" },
      ...(next === undefined ? {} : { next }),
    });
  }
  redirect(hrefFor(screenById("system.sign-in-email-sent")));
}

/** The sign-up form: the pending sign-in becomes a new tenant's first user and session. */
export async function signUp(_state: ActionState, formData: FormData): Promise<ActionState> {
  const parsed = parseSignUpForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const pending = await readPending();
  if (pending === null) redirect(`${signInHref()}?error=pending-expired`);
  const provider = providerFor(getEnv());
  if (!provider.ok) return toActionState<undefined>(err(provider.error));
  const ctx: SignInContext = { provider: provider.value, contact: pending.contact };
  if (pending.next !== undefined) ctx.next = pending.next;
  const step = await completeSignUp(ctx, pending, parsed.value);
  if (step.kind === "refused" && step.reason === "subject-registered") {
    redirect(`${signInHref()}?error=registered`);
  }
  return finishSignIn(step, {
    ...(pending.next === undefined ? {} : { next: pending.next }),
    newTenant: true,
  });
}

import "server-only";

import { redirect } from "next/navigation";
import type { SessionClaims } from "@/entities/session/types";
import { clearPendingCookie, setPendingCookie } from "@/server/auth/pending";
import type { SignInStep } from "@/server/auth/usecases";
import { err, toActionState } from "@/server/result";
import { homeFor, mfaHref, signUpHref } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, type ActionState } from "@/shared/lib/action-state";
import { safeNext } from "@/shared/lib/url";
import { setSessionCookie } from "@/server/session";

/**
 * How every sign-in action ends: a session is written and the person goes where they were
 * heading (a same-origin `next`) or to the role's home; a sign-up or a second factor keeps
 * the verified provider session in cw_pending and goes to that page; a refusal or an error is
 * the action's state, for the form to show. A new tenant's owner lands on onboarding.
 */
export const REFUSAL_MESSAGES = {
  "user-disabled": "signIn.refusal.userDisabled",
  "tenant-deleting": "signIn.refusal.tenantDeleting",
  "subject-registered": "signIn.refusal.subjectRegistered",
} as const;

export interface FinishOptions {
  next?: string;
  /** Where a new tenant's first user lands: onboarding. */
  newTenant?: boolean;
}

export function landingFor(claims: SessionClaims, options: FinishOptions): string {
  const fallback = options.newTenant ? hrefFor(screenById("owner.onboarding")) : homeFor(claims);
  return safeNext(options.next, fallback);
}

export async function finishSignIn<T>(
  step: SignInStep,
  options: FinishOptions = {},
): Promise<ActionState<T>> {
  switch (step.kind) {
    case "session":
      await setSessionCookie(step.claims);
      await clearPendingCookie();
      redirect(landingFor(step.claims, options));
    case "sign-up":
      await setPendingCookie(step.pending);
      redirect(signUpHref());
    case "mfa":
      await setPendingCookie(step.pending);
      redirect(mfaHref(options.next ?? step.pending.next));
    case "refused":
      return actionFailure(t(REFUSAL_MESSAGES[step.reason]));
    case "error":
      return toActionState<T>(err(step.error));
  }
}

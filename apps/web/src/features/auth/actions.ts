"use server";

import { redirect } from "next/navigation";
import { providerFor } from "@/server/auth/provider";
import type { FakeSignInInput } from "@/server/auth/provider";
import { getEnv } from "@/server/env";
import { err, toActionState } from "@/server/result";
import { setSessionCookie } from "@/server/session";
import { homeFor } from "@/shared/config/nav";
import type { Role, TenantKind } from "@/shared/config/roles";
import { fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { safeNext } from "@/shared/lib/url";
import { parseFakeSignInForm } from "./model/sign-in";

/**
 * The sign-in form's server action: shape-check the form, ask the configured provider for the
 * claims, write the cookie, and go where the visitor was heading (a same-origin `next`) or to
 * the role's home. Every expected failure is an ActionState; the redirect is the success.
 */
export async function signIn(_state: ActionState, formData: FormData): Promise<ActionState> {
  const parsed = parseFakeSignInForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const env = getEnv();
  const provider = providerFor(env);
  if (!provider.ok) return toActionState<undefined>(err(provider.error));
  const { tenantKind, roles, displayName, tenantId, next } = parsed.value;
  const input: FakeSignInInput = {
    kind: "fake",
    // The adapter validates the kind and the roles by value; the casts only name the type.
    tenantKind: tenantKind as TenantKind,
    roles: roles as readonly Role[],
    displayName,
    ...(tenantId === undefined ? {} : { tenantId }),
  };
  const session = await provider.value.completeSignIn(input, {
    now: new Date(),
    ttlSeconds: env.CW_WEB_SESSION_TTL_SECONDS,
  });
  if (!session.ok) return toActionState<undefined>(err(session.error));
  await setSessionCookie(session.value);
  redirect(safeNext(next, homeFor(session.value)));
}

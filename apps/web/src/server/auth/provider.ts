import "server-only";

import type { SessionClaims } from "@/entities/session/types";
import type { Role, TenantKind } from "@/shared/config/roles";
import { getEnv, type AuthProviderName, type WebEnv } from "../env";
import { err, ok, webError, type Result } from "../result";
import { FakeAuthProvider } from "./fake";

/**
 * The port the sign-in flow talks to. An adapter proves who the user is and answers the claims
 * the session cookie will carry; the pages, the actions and the session module never know
 * which adapter is behind it. Two adapters are named by CW_WEB_AUTH_PROVIDER:
 *
 *   fake      local and test only; mints a session for a chosen tenant, kind, roles and name
 *             (server/auth/fake.ts). The identity work changes its implementation to the dev
 *             provider tokens and the session exchange without renaming it.
 *   supabase  reserved; refused until its adapter exists (identity work, WP14).
 *
 * `startSignIn` opens a challenge (an OTP by SMS, an email link) and `completeSignIn` closes
 * it; the fake adapter has no challenge and completes in one step. Failures are `Result`
 * errors with a web-local problem, so a server action maps them like any service failure.
 */
export type SignInMethod = "fake" | "phone" | "email";

export interface FakeSignInInput {
  kind: "fake";
  /** An existing tenant id; absent or empty means a new tenant. */
  tenantId?: string;
  tenantKind: TenantKind;
  roles: readonly Role[];
  displayName: string;
}

export type StartSignInInput = { kind: "phone"; phone: string } | { kind: "email"; email: string };

export type CompleteSignInInput =
  | FakeSignInInput
  | { kind: "otp"; challengeId: string; code: string }
  | { kind: "email-link"; token: string };

export interface SignInChallenge {
  kind: "otp" | "email-sent";
  challengeId?: string;
}

export interface SignInContext {
  now: Date;
  /** The session lifetime the claims are issued for. */
  ttlSeconds: number;
}

export interface AuthProvider {
  readonly name: AuthProviderName;
  /** The sign-in methods the provider offers; the sign-in page renders the matching form. */
  readonly methods: readonly SignInMethod[];
  startSignIn(input: StartSignInInput): Promise<Result<SignInChallenge>>;
  completeSignIn(
    input: CompleteSignInInput,
    context: SignInContext,
  ): Promise<Result<SessionClaims>>;
  /** Ends the session at the provider; the cookie is cleared by the caller. */
  signOut(claims: SessionClaims): Promise<void>;
}

export const PROVIDER_VARIABLE = "CW_WEB_AUTH_PROVIDER";

/** The configured adapter, or the reason there is none (shown by the sign-in page). */
export function providerFor(env: WebEnv = getEnv()): Result<AuthProvider> {
  switch (env.CW_WEB_AUTH_PROVIDER) {
    case "fake":
      return ok(new FakeAuthProvider(env));
    case "supabase":
      return err(
        webError(
          "unavailable",
          "web-auth-provider-not-implemented",
          "Sign-in with supabase is not available yet",
          `${PROVIDER_VARIABLE} names the supabase adapter, which arrives with the identity work (WP14).`,
        ),
      );
    default:
      return err(
        webError(
          "unavailable",
          "web-auth-provider-missing",
          "Sign-in is not configured",
          `Set ${PROVIDER_VARIABLE} to fake (local and test only) or supabase.`,
        ),
      );
  }
}

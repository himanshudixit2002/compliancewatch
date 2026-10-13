import "server-only";

import type { Role, TenantKind } from "@/shared/config/roles";
import { getEnv, type AuthProviderName, type WebEnv } from "../env";
import type { FetchImpl } from "../api/client";
import { err, ok, webError, type ApiError, type ApiErrorKind, type Result } from "../result";
import { FakeAuthProvider } from "./fake";
import { SupabaseAuthProvider } from "./supabase";

/**
 * The port the sign-in flow talks to (ADR-014). An adapter proves who the person is at the
 * identity provider and answers a `ProviderSession`: the provider's own token, which the
 * server layer then exchanges with the identity service for the session the cookie carries
 * (server/auth/sessions.ts). The pages, the actions, the proxy and the session module never
 * know which adapter is behind it. Two adapters are named by CW_WEB_AUTH_PROVIDER:
 *
 *   fake      local and test only (server/auth/fake.ts): identity's development provider
 *             tokens; any six-digit code passes the OTP step, the email link is shown instead
 *             of sent, and the second factor is one confirm button. It also signs in as a
 *             development persona (a tenant kind, roles and a name), which identity makes on
 *             the spot: the form that stays on the sign-in page in local and test.
 *   supabase  Supabase Auth over GoTrue's REST API, server-side only (server/auth/supabase.ts).
 *
 * Every method answers a `Result`: a failure is an `ApiError` with a web-local problem
 * (`web-provider-<kind>`, `providerFailure`) that a server action maps like a service failure,
 * so no raw provider error reaches a form.
 */
export type SignInMethod = "dev" | "phone" | "email";

/** Authenticator assurance level: one factor, or a second factor verified in this session. */
export type Aal = "aal1" | "aal2";

export interface ProviderSession {
  /** The provider's token, which `POST /v1/identity/sessions` exchanges. */
  accessToken: string;
  /** What `refresh` takes to get a new access token; carried in the session cookie. */
  refreshToken: string;
  /** Seconds since the epoch. */
  expiresAt: number;
  aal: Aal;
  /** The provider's subject for the person, for logs and tests. */
  subject: string;
}

export interface MfaFactor {
  id: string;
  type: "totp";
  status: "verified" | "unverified";
  friendlyName: string;
}

export interface TotpEnrolment {
  factorId: string;
  /** An SVG of the QR code, from the provider. */
  qrSvg: string;
  /** The secret as text, for an app that cannot scan. */
  secret: string;
}

export interface MfaChallenge {
  challengeId: string;
  expiresAt: number;
}

export interface MfaPort {
  listFactors(session: ProviderSession): Promise<Result<MfaFactor[]>>;
  enrolTotp(session: ProviderSession, friendlyName: string): Promise<Result<TotpEnrolment>>;
  challenge(session: ProviderSession, factorId: string): Promise<Result<MfaChallenge>>;
  /** The session at aal2 once the code verifies. */
  verify(
    session: ProviderSession,
    factorId: string,
    challengeId: string,
    code: string,
  ): Promise<Result<ProviderSession>>;
  remove(session: ProviderSession, factorId: string): Promise<Result<void>>;
}

/** The development sign-in's input: who to be (fake adapter only). */
export interface DevPersonaInput {
  /** An existing tenant id; absent or empty means a new tenant. */
  tenantId?: string;
  tenantKind: TenantKind;
  roles: readonly Role[];
  displayName: string;
}

export interface EmailLinkSent {
  /** Local and test only: the link the fake adapter would have sent, since it sends nothing. */
  devLink?: string;
}

export interface AuthProvider {
  readonly name: AuthProviderName;
  /** The sign-in methods the provider offers; the sign-in page renders the matching forms. */
  readonly methods: readonly SignInMethod[];
  /** `totp`: enrol and challenge an authenticator app; `confirm`: one button asserts it (fake). */
  readonly mfaMode: "totp" | "confirm";
  startPhoneOtp(phone: string): Promise<Result<void>>;
  verifyPhoneOtp(phone: string, code: string): Promise<Result<ProviderSession>>;
  sendEmailLink(email: string, redirectTo: string): Promise<Result<EmailLinkSent>>;
  exchangeEmailLink(tokenHash: string): Promise<Result<ProviderSession>>;
  refresh(refreshToken: string): Promise<Result<ProviderSession>>;
  /** Ends the session at the provider; the cookie is cleared by the caller. Never throws. */
  signOut(refreshToken: string): Promise<void>;
  readonly mfa: MfaPort;
  /** The development sign-in: a persona identity makes on the spot (fake adapter only). */
  signInAsPersona?(input: DevPersonaInput): Promise<Result<ProviderSession>>;
}

export const PROVIDER_VARIABLE = "CW_WEB_AUTH_PROVIDER";

/** Why a provider refused, as the forms word it. */
export type ProviderFailureKind =
  | "invalid_code"
  | "expired"
  | "rate_limited"
  | "unavailable"
  | "invalid_link"
  | "invalid_contact"
  | "invalid_persona"
  | "unsupported";

const FAILURE_KINDS: Readonly<Record<ProviderFailureKind, Exclude<ApiErrorKind, "network">>> = {
  invalid_code: "bad_request",
  expired: "unauthenticated",
  rate_limited: "rate_limited",
  unavailable: "unavailable",
  invalid_link: "unauthenticated",
  invalid_contact: "validation",
  invalid_persona: "validation",
  unsupported: "bad_request",
};

const FAILURE_TITLES: Readonly<Record<ProviderFailureKind, string>> = {
  invalid_code: "That code is not right",
  expired: "That code has expired",
  rate_limited: "Too many attempts",
  unavailable: "The sign-in provider is not available right now",
  invalid_link: "That sign-in link is not valid any more",
  invalid_contact: "Check the phone number or email address",
  invalid_persona: "Check the sign-in details",
  unsupported: "The sign-in provider cannot do this",
};

export const PROVIDER_FAILURE_PREFIX = "web-provider-";

/** The ApiError for a provider's refusal: `urn:compliancewatch:problem:web-provider-<kind>`. */
export function providerFailure(
  kind: ProviderFailureKind,
  detail?: string,
  options: { retryAfterSeconds?: number; fieldErrors?: Record<string, string[]> } = {},
): ApiError {
  const error = webError(
    FAILURE_KINDS[kind],
    `${PROVIDER_FAILURE_PREFIX}${kind.replace(/_/g, "-")}`,
    FAILURE_TITLES[kind],
    detail,
    options.fieldErrors,
  );
  if (options.retryAfterSeconds !== undefined) error.retryAfterSeconds = options.retryAfterSeconds;
  return error;
}

/** The failure kind behind an ApiError a provider answered, or null for any other error. */
export function providerFailureKind(error: ApiError): ProviderFailureKind | null {
  const type = error.problem?.type ?? "";
  const marker = `:${PROVIDER_FAILURE_PREFIX}`;
  const at = type.indexOf(marker);
  if (at === -1) return null;
  const kind = type.slice(at + marker.length).replace(/-/g, "_");
  return Object.hasOwn(FAILURE_KINDS, kind) ? (kind as ProviderFailureKind) : null;
}

export interface ProviderDeps {
  /** What a test injects in place of fetch, for both adapters' calls. */
  fetchImpl?: FetchImpl;
}

/** The configured adapter, or the reason there is none (shown by the sign-in page). */
export function providerFor(env: WebEnv = getEnv(), deps: ProviderDeps = {}): Result<AuthProvider> {
  switch (env.CW_WEB_AUTH_PROVIDER) {
    case "fake":
      return ok(new FakeAuthProvider(env, deps));
    case "supabase":
      return ok(new SupabaseAuthProvider(env, deps));
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

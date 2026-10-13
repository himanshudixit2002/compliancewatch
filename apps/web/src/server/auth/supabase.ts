import "server-only";

import { epochSeconds } from "@/entities/session/mappers";
import { isE164, isEmailAddress } from "@/shared/lib/identifiers";
import type { FetchImpl } from "../api/client";
import { EnvError, type WebEnv } from "../env";
import { err, ok, type ApiError, type Result } from "../result";
import {
  providerFailure,
  type Aal,
  type AuthProvider,
  type EmailLinkSent,
  type MfaChallenge,
  type MfaFactor,
  type MfaPort,
  type ProviderSession,
  type SignInMethod,
  type TotpEnrolment,
} from "./provider";

/**
 * Supabase Auth as the sign-in provider, over GoTrue's REST API with fetch and nothing else:
 * no supabase-js, so the anon key stays on the server (D-067 in docs/web/decisions.md) and the
 * adapter is one module whose every call is checked against recorded response shapes
 * (src/test/gotrue-fixtures.ts) until the Supabase project exists. The endpoints, under
 * `{CW_WEB_SUPABASE_URL}/auth/v1`, each with `apikey: <anon key>` and, for a signed-in call,
 * `Authorization: Bearer <the person's access token>`:
 *
 *   POST /otp            {phone} or {email, create_user, redirect_to}   send a code or a link
 *   POST /verify         {type sms, phone, token} or {type magiclink, token_hash}
 *   POST /token?grant_type=refresh_token  {refresh_token}
 *   POST /logout
 *   GET  /factors, POST /factors {factor_type totp, friendly_name}, POST /factors/{id}/challenge,
 *   POST /factors/{id}/verify {challenge_id, code}, DELETE /factors/{id}
 *
 * A GoTrue error body is `{code, error_code, msg}` (or `{error, error_description}` on the
 * token route); the mapping to `ProviderFailure` kinds: 400 or 422 with an OTP code is
 * `invalid_code` (`otp_expired` is `expired`), 401 and 403 are `expired` (or `invalid_link` on
 * the magic-link verify), 429 is `rate_limited` with Retry-After, and a 5xx or no answer is
 * `unavailable`. The session's `aal` is read from the access token's claims; GoTrue signs the
 * token and the identity service verifies it, so this module never does.
 */
export const SUPABASE_METHODS: readonly SignInMethod[] = ["phone", "email"];

const AUTH_PATH = "/auth/v1";
const SUPABASE_TOKEN_TTL_SECONDS = 3_600;

/** The session GoTrue answers on sign-in, verify, refresh and factor verify. */
export interface GotrueSession {
  access_token: string;
  refresh_token: string;
  expires_in?: number;
  expires_at?: number;
  token_type?: string;
  user?: { id?: string; aud?: string; email?: string | null; phone?: string | null };
}

interface GotrueError {
  code?: number | string;
  error_code?: string;
  msg?: string;
  error?: string;
  error_description?: string;
}

interface GotrueFactor {
  id: string;
  friendly_name?: string | null;
  factor_type: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

interface GotrueFactorsOut {
  all?: GotrueFactor[];
  totp?: GotrueFactor[];
}

interface GotrueEnrolOut {
  id: string;
  type: string;
  totp?: { qr_code?: string; secret?: string; uri?: string };
}

interface GotrueChallengeOut {
  id: string;
  expires_at?: number;
}

function unverifiedClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const parsed: unknown = JSON.parse(Buffer.from(parts[1] as string, "base64url").toString());
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** The ProviderSession of a GoTrue session; null when the body is not one. */
export function sessionFromGotrue(body: unknown, now: Date = new Date()): ProviderSession | null {
  if (typeof body !== "object" || body === null) return null;
  const session = body as Partial<GotrueSession>;
  if (typeof session.access_token !== "string" || session.access_token === "") return null;
  if (typeof session.refresh_token !== "string" || session.refresh_token === "") return null;
  const claims = unverifiedClaims(session.access_token);
  const aal: Aal = claims?.aal === "aal2" ? "aal2" : "aal1";
  const subject = typeof claims?.sub === "string" ? claims.sub : (session.user?.id ?? "");
  const expiresAt =
    typeof session.expires_at === "number"
      ? session.expires_at
      : epochSeconds(now) +
        (typeof session.expires_in === "number" ? session.expires_in : SUPABASE_TOKEN_TTL_SECONDS);
  return {
    accessToken: session.access_token,
    refreshToken: session.refresh_token,
    expiresAt,
    aal,
    subject,
  };
}

function retryAfter(response: Response): number | undefined {
  const value = response.headers.get("retry-after");
  if (value === null || !/^\d+$/.test(value.trim())) return undefined;
  return Number(value.trim());
}

/** What a GoTrue refusal means to the person at the form. */
export function mapGotrueError(
  status: number,
  body: GotrueError | null,
  context: "otp" | "verify" | "magiclink" | "refresh" | "mfa" | "logout",
  retryAfterSeconds?: number,
): ApiError {
  const code = body?.error_code ?? body?.error ?? "";
  const detail = body?.msg ?? body?.error_description ?? undefined;
  if (status === 429) return providerFailure("rate_limited", detail, { retryAfterSeconds });
  if (status >= 500) return providerFailure("unavailable", detail);
  if (code === "otp_expired") return providerFailure("expired", detail);
  if (code === "over_sms_send_rate_limit" || code === "over_email_send_rate_limit") {
    return providerFailure("rate_limited", detail, { retryAfterSeconds });
  }
  if (context === "magiclink") return providerFailure("invalid_link", detail);
  if (context === "verify" || context === "mfa") {
    if (status === 400 || status === 422) {
      return providerFailure("invalid_code", detail, {
        fieldErrors: { code: ["Check the code."] },
      });
    }
    return providerFailure("expired", detail);
  }
  if (context === "refresh") return providerFailure("expired", detail);
  if (status === 400 || status === 422) {
    return providerFailure("invalid_contact", detail, {
      fieldErrors: { contact: [detail ?? "The provider refused this address."] },
    });
  }
  return providerFailure("unavailable", detail);
}

export class SupabaseAuthProvider implements AuthProvider {
  readonly name = "supabase";
  readonly methods = SUPABASE_METHODS;
  readonly mfaMode = "totp";
  readonly mfa: MfaPort;
  private readonly baseUrl: string;
  private readonly anonKey: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: FetchImpl;

  constructor(env: WebEnv, deps: { fetchImpl?: FetchImpl } = {}) {
    if (env.CW_WEB_SUPABASE_URL === undefined || env.CW_WEB_SUPABASE_ANON_KEY === undefined) {
      throw new EnvError(
        "the supabase sign-in provider needs CW_WEB_SUPABASE_URL and CW_WEB_SUPABASE_ANON_KEY",
      );
    }
    this.baseUrl = `${env.CW_WEB_SUPABASE_URL}${AUTH_PATH}`;
    this.anonKey = env.CW_WEB_SUPABASE_ANON_KEY;
    this.timeoutMs = env.CW_WEB_REQUEST_TIMEOUT_MS;
    this.fetchImpl = deps.fetchImpl ?? ((input, init) => fetch(input, init));
    this.mfa = {
      listFactors: (session) => this.listFactors(session),
      enrolTotp: (session, friendlyName) => this.enrolTotp(session, friendlyName),
      challenge: (session, factorId) => this.challenge(session, factorId),
      verify: (session, factorId, challengeId, code) =>
        this.verify(session, factorId, challengeId, code),
      remove: (session, factorId) => this.remove(session, factorId),
    };
  }

  async startPhoneOtp(phone: string): Promise<Result<void>> {
    if (!isE164(phone)) return err(invalidContact("phone"));
    const result = await this.request("POST", "/otp", { body: { phone }, context: "otp" });
    return result.ok ? ok(undefined) : result;
  }

  async verifyPhoneOtp(phone: string, code: string): Promise<Result<ProviderSession>> {
    if (!isE164(phone)) return err(invalidContact("phone"));
    const result = await this.request("POST", "/verify", {
      body: { type: "sms", phone, token: code.trim() },
      context: "verify",
    });
    return result.ok ? this.session(result.value) : result;
  }

  async sendEmailLink(email: string, redirectTo: string): Promise<Result<EmailLinkSent>> {
    if (!isEmailAddress(email)) return err(invalidContact("email"));
    const result = await this.request("POST", "/otp", {
      body: { email: email.trim().toLowerCase(), create_user: true },
      query: { redirect_to: redirectTo },
      context: "otp",
    });
    return result.ok ? ok({}) : result;
  }

  async exchangeEmailLink(tokenHash: string): Promise<Result<ProviderSession>> {
    const result = await this.request("POST", "/verify", {
      body: { type: "magiclink", token_hash: tokenHash },
      context: "magiclink",
    });
    return result.ok ? this.session(result.value) : result;
  }

  async refresh(refreshToken: string): Promise<Result<ProviderSession>> {
    const result = await this.request("POST", "/token", {
      body: { refresh_token: refreshToken },
      query: { grant_type: "refresh_token" },
      context: "refresh",
    });
    return result.ok ? this.session(result.value) : result;
  }

  /** Revokes the refresh token's session at GoTrue; a failure is logged, never thrown. */
  async signOut(refreshToken: string): Promise<void> {
    const refreshed = await this.refresh(refreshToken);
    if (!refreshed.ok) return;
    const result = await this.request("POST", "/logout", {
      query: { scope: "local" },
      token: refreshed.value.accessToken,
      context: "logout",
      empty: true,
    });
    if (!result.ok) {
      console.warn(
        JSON.stringify({
          level: "warn",
          event: "supabase_sign_out_failed",
          message: result.error.message,
        }),
      );
    }
  }

  private async listFactors(session: ProviderSession): Promise<Result<MfaFactor[]>> {
    const result = await this.request("GET", "/factors", {
      token: session.accessToken,
      context: "mfa",
    });
    if (!result.ok) return result;
    const body = result.value as GotrueFactorsOut | GotrueFactor[] | null;
    const list = Array.isArray(body) ? body : (body?.all ?? body?.totp ?? []);
    return ok(
      list
        .filter((factor) => factor.factor_type === "totp")
        .map((factor) => ({
          id: factor.id,
          type: "totp" as const,
          status: factor.status === "verified" ? ("verified" as const) : ("unverified" as const),
          friendlyName: factor.friendly_name ?? "",
        })),
    );
  }

  private async enrolTotp(
    session: ProviderSession,
    friendlyName: string,
  ): Promise<Result<TotpEnrolment>> {
    const result = await this.request("POST", "/factors", {
      body: { factor_type: "totp", friendly_name: friendlyName, issuer: "ComplianceWatch" },
      token: session.accessToken,
      context: "mfa",
    });
    if (!result.ok) return result;
    const body = result.value as GotrueEnrolOut | null;
    if (body === null || typeof body.id !== "string" || body.totp === undefined) {
      return err(
        providerFailure("unavailable", "Supabase answered an enrolment without a factor."),
      );
    }
    return ok({
      factorId: body.id,
      qrSvg: body.totp.qr_code ?? "",
      secret: body.totp.secret ?? "",
    });
  }

  private async challenge(
    session: ProviderSession,
    factorId: string,
  ): Promise<Result<MfaChallenge>> {
    const result = await this.request(
      "POST",
      `/factors/${encodeURIComponent(factorId)}/challenge`,
      {
        body: {},
        token: session.accessToken,
        context: "mfa",
      },
    );
    if (!result.ok) return result;
    const body = result.value as GotrueChallengeOut | null;
    if (body === null || typeof body.id !== "string") {
      return err(providerFailure("unavailable", "Supabase answered a challenge without an id."));
    }
    return ok({
      challengeId: body.id,
      expiresAt:
        typeof body.expires_at === "number" ? body.expires_at : epochSeconds(new Date()) + 300,
    });
  }

  private async verify(
    session: ProviderSession,
    factorId: string,
    challengeId: string,
    code: string,
  ): Promise<Result<ProviderSession>> {
    const result = await this.request("POST", `/factors/${encodeURIComponent(factorId)}/verify`, {
      body: { challenge_id: challengeId, code: code.trim() },
      token: session.accessToken,
      context: "mfa",
    });
    return result.ok ? this.session(result.value) : result;
  }

  private async remove(session: ProviderSession, factorId: string): Promise<Result<void>> {
    const result = await this.request("DELETE", `/factors/${encodeURIComponent(factorId)}`, {
      token: session.accessToken,
      context: "mfa",
      empty: true,
    });
    return result.ok ? ok(undefined) : result;
  }

  private session(body: unknown): Result<ProviderSession> {
    const session = sessionFromGotrue(body);
    return session === null
      ? err(providerFailure("unavailable", "Supabase answered without a session."))
      : ok(session);
  }

  /** One GoTrue call: the parsed JSON body of a 2xx, or the mapped failure. */
  private async request(
    method: "GET" | "POST" | "DELETE",
    path: string,
    options: {
      body?: unknown;
      query?: Record<string, string>;
      token?: string;
      context: "otp" | "verify" | "magiclink" | "refresh" | "mfa" | "logout";
      empty?: boolean;
    },
  ): Promise<Result<unknown>> {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.query ?? {}))
      url.searchParams.set(key, value);
    const headers: Record<string, string> = { apikey: this.anonKey, accept: "application/json" };
    if (options.token !== undefined) headers.authorization = `Bearer ${options.token}`;
    const init: RequestInit = { method, headers };
    if (options.body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    let response: Response;
    try {
      response = await this.fetchImpl(new Request(url, init), {
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (cause) {
      const timedOut = cause instanceof Error && cause.name === "TimeoutError";
      return err(
        providerFailure(
          "unavailable",
          timedOut
            ? `Supabase did not answer within ${this.timeoutMs} ms.`
            : "Supabase could not be reached.",
        ),
      );
    }
    const text = await response.text();
    let parsed: unknown = null;
    if (text !== "") {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
    }
    if (!response.ok) {
      const body = typeof parsed === "object" && parsed !== null ? (parsed as GotrueError) : null;
      return err(mapGotrueError(response.status, body, options.context, retryAfter(response)));
    }
    if (options.empty) return ok(undefined);
    return ok(parsed);
  }
}

function invalidContact(field: "phone" | "email"): ApiError {
  const message =
    field === "phone"
      ? "Enter a mobile number with its country code, such as +919876543210."
      : "Enter an email address.";
  return providerFailure("invalid_contact", undefined, { fieldErrors: { [field]: [message] } });
}

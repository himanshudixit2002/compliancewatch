import "server-only";

import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";
import { z } from "zod";
import { AUTH_PROVIDER_NAMES, getEnv, requireSessionSecret, type WebEnv } from "../env";
import type { ProviderSession } from "./provider";

/**
 * The pending sign-in: a person who proved who they are at the provider but has no session
 * yet, because identity answered that they must sign up (no user for this sign-in) or verify a
 * second factor first. The verified provider session travels between /sign-in, /sign-up and
 * /account/mfa in `cw_pending`, a JWE under the session secret like `cw_session`, httpOnly,
 * SameSite=Lax, Secure outside local, and good for five minutes; never in a URL (D-068).
 * `signUp` keeps what the sign-up form sent when the tenant's first role needs a second
 * factor (a CA firm), so the MFA confirm can finish the sign-up without asking again.
 */
export const PENDING_COOKIE_NAME = "cw_pending";
export const PENDING_TTL_SECONDS = 300;

const KEY_MANAGEMENT = "dir";
const CONTENT_ENCRYPTION = "A256GCM";

const contactSchema = z.object({
  phone: z.string().min(1).optional(),
  email: z.string().min(1).optional(),
});

const providerSessionSchema = z.object({
  accessToken: z.string().min(1),
  refreshToken: z.string().min(1),
  expiresAt: z.number().int(),
  aal: z.enum(["aal1", "aal2"]),
  subject: z.string(),
});

const signUpSchema = z.object({
  kind: z.enum(["business", "ca_firm"]),
  name: z.string().min(1),
  displayName: z.string(),
});

const pendingSchema = z.object({
  provider: z.enum(AUTH_PROVIDER_NAMES),
  session: providerSessionSchema,
  contact: contactSchema,
  next: z.string().optional(),
  signUp: signUpSchema.optional(),
  iat: z.number().int(),
  exp: z.number().int(),
});

export type PendingContact = z.output<typeof contactSchema>;
export type PendingSignUp = z.output<typeof signUpSchema>;

export interface PendingSignIn {
  provider: (typeof AUTH_PROVIDER_NAMES)[number];
  session: ProviderSession;
  contact: PendingContact;
  /** The same-origin path to return to once signed in. */
  next?: string;
  signUp?: PendingSignUp;
}

function strip<T extends Record<string, unknown>>(value: T): T {
  const copy = { ...value };
  for (const key of Object.keys(copy)) if (copy[key] === undefined) delete copy[key];
  return copy;
}

export async function encryptPending(
  pending: PendingSignIn,
  key: Uint8Array = requireSessionSecret(),
  now: Date = new Date(),
): Promise<string> {
  const iat = Math.floor(now.getTime() / 1000);
  const payload = strip({ ...pending, contact: strip(pending.contact) });
  return new EncryptJWT({ ...payload })
    .setProtectedHeader({ alg: KEY_MANAGEMENT, enc: CONTENT_ENCRYPTION })
    .setIssuedAt(iat)
    .setExpirationTime(iat + PENDING_TTL_SECONDS)
    .encrypt(key);
}

/** The pending sign-in behind a cookie value, or null for anything else (never throws). */
export async function decryptPending(
  token: string,
  key: Uint8Array = requireSessionSecret(),
  now: Date = new Date(),
): Promise<PendingSignIn | null> {
  try {
    const { payload } = await jwtDecrypt(token, key, {
      keyManagementAlgorithms: [KEY_MANAGEMENT],
      contentEncryptionAlgorithms: [CONTENT_ENCRYPTION],
      currentDate: now,
    });
    const parsed = pendingSchema.safeParse(payload);
    if (!parsed.success) return null;
    const { data } = parsed;
    const pending: PendingSignIn = {
      provider: data.provider,
      session: data.session,
      contact: strip(data.contact),
    };
    if (data.next !== undefined) pending.next = data.next;
    if (data.signUp !== undefined) pending.signUp = data.signUp;
    return pending;
  } catch {
    return null;
  }
}

export function pendingCookieOptions(env: WebEnv = getEnv()) {
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    secure: env.CW_WEB_ENV !== "local",
    path: "/" as const,
    maxAge: PENDING_TTL_SECONDS,
  };
}

/** The pending sign-in of the request, if any (a render may read). */
export async function readPending(): Promise<PendingSignIn | null> {
  const value = (await cookies()).get(PENDING_COOKIE_NAME)?.value;
  if (value === undefined || value === "") return null;
  return decryptPending(value);
}

/** Writes the pending cookie. Server actions and route handlers only. */
export async function setPendingCookie(pending: PendingSignIn): Promise<void> {
  (await cookies()).set(PENDING_COOKIE_NAME, await encryptPending(pending), pendingCookieOptions());
}

/** Expires the pending cookie. Server actions and route handlers only. */
export async function clearPendingCookie(): Promise<void> {
  (await cookies()).set(PENDING_COOKIE_NAME, "", { ...pendingCookieOptions(), maxAge: 0 });
}

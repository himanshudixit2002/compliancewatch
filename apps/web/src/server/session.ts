import "server-only";

import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";
import { z } from "zod";
import { SESSION_COOKIE_NAME, SESSION_PROVIDERS } from "@/entities/session/types";
import type { SessionClaims } from "@/entities/session/types";
import { ROLES, TENANT_KINDS } from "@/shared/config/roles";
import { getEnv, requireSessionSecret, type WebEnv } from "./env";

/**
 * The stateless session: the claims travel in `cw_session`, a JWE the server encrypts with
 * the 32-byte CW_WEB_SESSION_SECRET (`dir` key management, A256GCM), httpOnly, SameSite=Lax,
 * Secure outside local, scoped to `/`, and expiring with the claims (CW_WEB_SESSION_TTL_SECONDS,
 * eight hours by default). The browser holds ciphertext it cannot read or forge; the server
 * holds no session table. Rotation and the identity `/me` re-read arrive with the real sign-in
 * and run in the proxy, never during a render.
 *
 * `cookies().set` works only in a server action or a route handler (Next 16), so
 * `setSessionCookie` and `clearSessionCookie` are called from `features/auth/actions.ts` and
 * `app/sign-out/route.ts`; a page reads through `server/dal.ts`. The secret is required only
 * here: a build and the public pages never encrypt or decrypt anything.
 */
const KEY_MANAGEMENT = "dir";
const CONTENT_ENCRYPTION = "A256GCM";

/** The JWT payload the cookie carries: the claims with the registered `iat` and `exp`. */
const payloadSchema = z.object({
  userId: z.string().min(1),
  tenantId: z.string().min(1),
  tenantKind: z.enum(TENANT_KINDS),
  roles: z.array(z.enum(ROLES)).min(1),
  displayName: z.string().min(1),
  mfa: z.boolean(),
  sv: z.number().int().nonnegative(),
  provider: z.enum(SESSION_PROVIDERS),
  iat: z.number().int(),
  exp: z.number().int(),
  cwToken: z.string().min(1).optional(),
  cwTokenExpiresAt: z.number().int().optional(),
  providerRefreshToken: z.string().min(1).optional(),
  checkedAt: z.number().int().optional(),
  analyticsConsent: z.boolean().optional(),
});

type Payload = z.output<typeof payloadSchema>;

function toPayload(claims: SessionClaims): Payload {
  const { issuedAt, expiresAt, ...rest } = claims;
  const payload: Payload = { ...rest, roles: [...claims.roles], iat: issuedAt, exp: expiresAt };
  // Absent optional fields stay absent rather than travelling as null.
  for (const key of Object.keys(payload) as (keyof Payload)[]) {
    if (payload[key] === undefined) delete payload[key];
  }
  return payload;
}

/** The claims from a verified payload; null when the shape is not a session. */
export function claimsFromPayload(payload: unknown): SessionClaims | null {
  const parsed = payloadSchema.safeParse(payload);
  if (!parsed.success) return null;
  const { iat, exp, ...rest } = parsed.data;
  return { ...rest, issuedAt: iat, expiresAt: exp };
}

/** The cookie as a compact JWE; the key defaults to the environment's secret. */
export async function encryptSession(
  claims: SessionClaims,
  key: Uint8Array = requireSessionSecret(),
): Promise<string> {
  const payload = toPayload(claims);
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: KEY_MANAGEMENT, enc: CONTENT_ENCRYPTION })
    .setIssuedAt(payload.iat)
    .setExpirationTime(payload.exp)
    .encrypt(key);
}

/**
 * The claims behind a cookie value, or null for anything that is not a valid, unexpired
 * session under this key: a tampered or truncated token, one from another secret, an expired
 * one, or a payload with the wrong shape. Nothing here throws for a bad token; a missing secret
 * still throws, because that is a configuration error and not a bad request.
 */
export async function decryptSession(
  token: string,
  key: Uint8Array = requireSessionSecret(),
  now: Date = new Date(),
): Promise<SessionClaims | null> {
  try {
    const { payload } = await jwtDecrypt(token, key, {
      keyManagementAlgorithms: [KEY_MANAGEMENT],
      contentEncryptionAlgorithms: [CONTENT_ENCRYPTION],
      currentDate: now,
    });
    return claimsFromPayload(payload);
  } catch {
    return null;
  }
}

export interface SessionCookieOptions {
  httpOnly: true;
  sameSite: "lax";
  secure: boolean;
  path: "/";
  maxAge: number;
}

/** httpOnly, SameSite=Lax, Secure outside local, the session lifetime as Max-Age. */
export function sessionCookieOptions(env: WebEnv = getEnv()): SessionCookieOptions {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: env.CW_WEB_ENV !== "local",
    path: "/",
    maxAge: env.CW_WEB_SESSION_TTL_SECONDS,
  };
}

/** The raw cookie value of the request, if any (a render may read; only actions may write). */
export async function readSessionCookie(): Promise<string | undefined> {
  const value = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  return value === undefined || value === "" ? undefined : value;
}

/** Writes the session cookie. Server actions and route handlers only. */
export async function setSessionCookie(claims: SessionClaims): Promise<void> {
  const token = await encryptSession(claims);
  (await cookies()).set(SESSION_COOKIE_NAME, token, sessionCookieOptions());
}

/** Expires the session cookie. Server actions and route handlers only. */
export async function clearSessionCookie(): Promise<void> {
  (await cookies()).set(SESSION_COOKIE_NAME, "", { ...sessionCookieOptions(), maxAge: 0 });
}

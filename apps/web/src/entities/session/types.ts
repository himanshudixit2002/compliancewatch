/**
 * The session: what the encrypted `cw_session` cookie carries and what a render may see of it.
 *
 * The claims are the minimum the server layer needs on every request: who the user is, which
 * tenant they act in, their roles, and the facts the gates read (second factor, session
 * version). No profile data and no personal identifier beyond the display name travels here;
 * `GET /v1/identity/me` supplies the rest when the identity work lands.
 *
 * The role and tenant-kind names mirror `shared/config/roles.ts` (entities import `shared/lib`
 * only); `types.test.ts` holds the compile-time check that the two lists are identical, so a
 * role added there fails here.
 */
export type SessionRole =
  | "owner"
  | "staff"
  | "ca_admin"
  | "ca_staff"
  | "compliance_lead"
  | "analyst"
  | "reviewer"
  | "admin";

export type SessionTenantKind = "business" | "ca_firm" | "internal";

/** Which adapter minted the session: the local fake, or the identity provider. */
export type SessionProvider = "fake" | "supabase";

export const SESSION_PROVIDERS: readonly SessionProvider[] = ["fake", "supabase"];

/** The cookie name; the proxy checks its presence, the data access layer decrypts it. */
export const SESSION_COOKIE_NAME = "cw_session";

export interface SessionClaims {
  userId: string;
  tenantId: string;
  tenantKind: SessionTenantKind;
  roles: readonly SessionRole[];
  displayName: string;
  /** Whether a second factor was verified for this session (the fake provider asserts it). */
  mfa: boolean;
  /** The session version identity keeps per user; a bump revokes older sessions. */
  sv: number;
  provider: SessionProvider;
  /** Seconds since the epoch. */
  issuedAt: number;
  expiresAt: number;
  /** The bearer token for the services, once identity issues one. */
  cwToken?: string;
  cwTokenExpiresAt?: number;
  providerRefreshToken?: string;
  /** When `/me` was last re-read, for the refresh done in the proxy. */
  checkedAt?: number;
  analyticsConsent?: boolean;
}

/** What a shell or a page receives: the session facts, never a token. */
export interface SessionDto {
  userId: string;
  tenantId: string;
  tenantKind: SessionTenantKind;
  roles: readonly SessionRole[];
  displayName: string;
  mfa: boolean;
  provider: SessionProvider;
  issuedAt: number;
  expiresAt: number;
}

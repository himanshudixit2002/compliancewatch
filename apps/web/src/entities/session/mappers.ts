import type { SessionClaims, SessionDto } from "./types";

/** The render-safe view of a session: the facts, without the token fields. */
export function toSessionDto(claims: SessionClaims): SessionDto {
  return {
    userId: claims.userId,
    tenantId: claims.tenantId,
    tenantKind: claims.tenantKind,
    roles: claims.roles,
    displayName: claims.displayName,
    mfa: claims.mfa,
    provider: claims.provider,
    issuedAt: claims.issuedAt,
    expiresAt: claims.expiresAt,
  };
}

/** Whole seconds since the epoch for an instant. */
export function epochSeconds(instant: Date): number {
  return Math.floor(instant.getTime() / 1000);
}

/** The issue and expiry instants of a session created now with the given lifetime. */
export function sessionWindow(
  now: Date,
  ttlSeconds: number,
): Pick<SessionClaims, "issuedAt" | "expiresAt"> {
  if (!Number.isInteger(ttlSeconds) || ttlSeconds <= 0) {
    throw new Error(`session lifetime must be a positive number of seconds, got ${ttlSeconds}`);
  }
  const issuedAt = epochSeconds(now);
  return { issuedAt, expiresAt: issuedAt + ttlSeconds };
}

/** Seconds left before the session expires; zero once it has. */
export function secondsUntilExpiry(claims: Pick<SessionClaims, "expiresAt">, now: Date): number {
  return Math.max(0, claims.expiresAt - epochSeconds(now));
}

export function isSessionExpired(claims: Pick<SessionClaims, "expiresAt">, now: Date): boolean {
  return secondsUntilExpiry(claims, now) === 0;
}

/** The expiry as an instant, for display. */
export function expiresAtDate(claims: Pick<SessionClaims, "expiresAt">): Date {
  return new Date(claims.expiresAt * 1000);
}

/**
 * Format checks for the identifiers the app handles. These are shape checks only: the services
 * validate checksums and existence. Identifiers are personal data, so they travel in POST
 * bodies or cookies, never in URLs, and are masked when shown outside the owner's own screens.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
/** State code, PAN, entity number, "Z", check character. */
const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const E164 = /^\+[1-9][0-9]{7,14}$/;
const HEX_ID = /^[0-9a-f]{32}$/;
/** Something@domain.tld, no spaces; the mail provider is the real check. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const EMAIL_MAX_LENGTH = 254;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

export function isPan(value: string): boolean {
  return PAN.test(value);
}

export function isGstin(value: string): boolean {
  return GSTIN.test(value);
}

/** An international phone number as the notification service stores it. */
export function isE164(value: string): boolean {
  return E164.test(value);
}

/** An email address's shape, at most 254 characters (RFC 5321's limit). */
export function isEmailAddress(value: string): boolean {
  return value.length <= EMAIL_MAX_LENGTH && EMAIL.test(value);
}

/** Rulebook document ids are 32 hex characters. */
export function isHexId(value: string): boolean {
  return HEX_ID.test(value);
}

/** Upper-cases and strips spaces so a pasted value compares cleanly. */
export function normaliseIdentifier(value: string): string {
  return value.replace(/\s+/g, "").toUpperCase();
}

/** The two-digit state code in front of a GSTIN. */
export function gstinStateCode(gstin: string): string {
  if (!isGstin(gstin)) throw new Error("not a GSTIN");
  return gstin.slice(0, 2);
}

/** The PAN embedded in a GSTIN. */
export function panOfGstin(gstin: string): string {
  if (!isGstin(gstin)) throw new Error("not a GSTIN");
  return gstin.slice(2, 12);
}

/** Keeps the last `visible` characters: "27ABCDE1234F1Z5" -> "***********1Z5". */
export function maskIdentifier(value: string, visible = 3): string {
  if (value.length <= visible) return value;
  return `${"*".repeat(value.length - visible)}${value.slice(-visible)}`;
}

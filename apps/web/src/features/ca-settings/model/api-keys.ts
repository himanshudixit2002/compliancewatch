import type { Tone } from "@compliancewatch/ui";
import type { MessageKey } from "@/shared/i18n";

/**
 * The API keys screen's model: the keys a tenant made for calling the service from its own
 * systems, as `GET /v1/identity/api-keys` (not scheduled yet) would list them. The service keeps
 * a hash of each secret, so a listed key carries only its first and last characters; the whole
 * secret exists once, in the answer to the call that created it.
 */
export type ApiKeyStatus = "active" | "revoked";

export interface ApiKey {
  id: string;
  /** The name given to the key, such as the system that uses it. */
  name: string;
  /** The key's first characters, which say what kind of key it is ("cw_live_"). */
  prefix: string;
  /** The key's last four characters, to tell keys apart. */
  lastFour: string;
  /** An ISO instant. */
  createdAt: string;
  /** The last call made with the key; null when it was never used. */
  lastUsedAt: string | null;
  /** When the key was revoked; null while it works. */
  revokedAt: string | null;
}

/** A key the create call has just made, with the one copy of its secret there will ever be. */
export interface NewApiKey {
  name: string;
  secret: string;
}

export interface ApiKeyCounts {
  total: number;
  active: number;
  revoked: number;
}

/** The form fields the create and revoke actions read. */
export const API_KEY_FIELDS = { name: "name", keyId: "key_id" } as const;

/** The longest name a key may be given. */
export const API_KEY_NAME_MAX = 80;

/** At most this many leading characters of a listed key are shown. */
export const KEY_PREFIX_SHOWN = 12;

export const API_KEY_STATUS_LABEL: Readonly<Record<ApiKeyStatus, MessageKey>> = {
  active: "caSettings.apiKeys.status.active",
  revoked: "caSettings.apiKeys.status.revoked",
};

export const API_KEY_STATUS_TONE: Readonly<Record<ApiKeyStatus, Tone>> = {
  active: "success",
  revoked: "neutral",
};

export function apiKeyStatus(key: Pick<ApiKey, "revokedAt">): ApiKeyStatus {
  return key.revokedAt === null ? "active" : "revoked";
}

/**
 * How a listed key is shown: its prefix and last four characters around an ellipsis
 * ("cw_live_…3f9a"). Both parts are cut to their limits, so a list that carried more of the key
 * than it should still never puts the whole secret on the page.
 */
export function keyHint(key: Pick<ApiKey, "prefix" | "lastFour">): string {
  return `${key.prefix.slice(0, KEY_PREFIX_SHOWN)}…${key.lastFour.slice(-4)}`;
}

/** Working keys first, then the most recently created. */
export function sortApiKeys(keys: readonly ApiKey[]): ApiKey[] {
  return [...keys].sort((a, b) => {
    const byStatus = Number(a.revokedAt !== null) - Number(b.revokedAt !== null);
    return byStatus !== 0 ? byStatus : Date.parse(b.createdAt) - Date.parse(a.createdAt);
  });
}

export function apiKeyCounts(keys: readonly ApiKey[]): ApiKeyCounts {
  const active = keys.filter((key) => key.revokedAt === null).length;
  return { total: keys.length, active, revoked: keys.length - active };
}

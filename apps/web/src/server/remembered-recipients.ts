import "server-only";

import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";
import { CHANNELS, isRecipientKey } from "@/entities/notification/mappers";
import type { Channel } from "@/entities/notification/types";
import { getEnv, requireSessionSecret, type WebEnv } from "./env";

/**
 * The notification recipients a user last named on this device: the WhatsApp number the consent
 * step opted in, or the number and address chosen on the notifications page. The identity
 * service does not return a user's own phone or email yet (GET /v1/identity/me is awaited), so
 * the settings pages remember them here instead of asking on every visit.
 *
 * The cookie `cw_prefs_recipient` is a JWE under the session key (the same `dir`/A256GCM as the
 * session), httpOnly, SameSite=Lax, Secure outside local, scoped to /settings and kept for 30
 * days. It carries the user id it belongs to, so after another user signs in on the same browser
 * it reads as empty. Values are the notification service's keys: a WhatsApp number as digits
 * without the plus, an email address lowercased. Pages read it; only server actions write it
 * (Next allows cookies().set in a Server Function or Route Handler, never during a render), and
 * signing out expires it.
 */
export const RECIPIENT_COOKIE_NAME = "cw_prefs_recipient";
export const RECIPIENT_COOKIE_PATH = "/settings";
export const RECIPIENT_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

const KIND = "cw-recipients";
const KEY_MANAGEMENT = "dir";
const CONTENT_ENCRYPTION = "A256GCM";

export type RememberedRecipients = Partial<Record<Channel, string>>;

export interface RecipientCookieOptions {
  httpOnly: true;
  sameSite: "lax";
  secure: boolean;
  path: typeof RECIPIENT_COOKIE_PATH;
  maxAge: number;
}

export function recipientCookieOptions(env: WebEnv = getEnv()): RecipientCookieOptions {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: env.CW_WEB_ENV !== "local",
    path: RECIPIENT_COOKIE_PATH,
    maxAge: RECIPIENT_COOKIE_MAX_AGE_SECONDS,
  };
}

/** The cookie value for this user's recipients; the key defaults to the session secret. */
export async function encryptRecipients(
  userId: string,
  recipients: RememberedRecipients,
  key: Uint8Array = requireSessionSecret(),
  now: Date = new Date(),
): Promise<string> {
  const issuedAt = Math.floor(now.getTime() / 1000);
  return new EncryptJWT({ kind: KIND, ...recipients })
    .setProtectedHeader({ alg: KEY_MANAGEMENT, enc: CONTENT_ENCRYPTION })
    .setSubject(userId)
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + RECIPIENT_COOKIE_MAX_AGE_SECONDS)
    .encrypt(key);
}

/**
 * The recipients a cookie value holds for this user; empty for another user's cookie, an
 * expired or tampered one, one from another key, or a value that is not a recipient key.
 */
export async function decryptRecipients(
  token: string,
  userId: string,
  key: Uint8Array = requireSessionSecret(),
  now: Date = new Date(),
): Promise<RememberedRecipients> {
  try {
    const { payload } = await jwtDecrypt(token, key, {
      keyManagementAlgorithms: [KEY_MANAGEMENT],
      contentEncryptionAlgorithms: [CONTENT_ENCRYPTION],
      currentDate: now,
      subject: userId,
    });
    if (payload.kind !== KIND) return {};
    const recipients: RememberedRecipients = {};
    for (const channel of CHANNELS) {
      const value = payload[channel];
      if (typeof value === "string" && isRecipientKey(channel, value)) recipients[channel] = value;
    }
    return recipients;
  } catch {
    return {};
  }
}

/** What this device remembers for the user; empty when nothing is remembered. */
export async function readRememberedRecipients(userId: string): Promise<RememberedRecipients> {
  const token = (await cookies()).get(RECIPIENT_COOKIE_NAME)?.value;
  if (token === undefined || token === "") return {};
  return decryptRecipients(token, userId);
}

async function writeRecipients(userId: string, recipients: RememberedRecipients): Promise<void> {
  const store = await cookies();
  if (Object.keys(recipients).length === 0) {
    store.set(RECIPIENT_COOKIE_NAME, "", { ...recipientCookieOptions(), maxAge: 0 });
    return;
  }
  store.set(
    RECIPIENT_COOKIE_NAME,
    await encryptRecipients(userId, recipients),
    recipientCookieOptions(),
  );
}

/** Remembers the recipient (a service key) for the channel. Server actions only. */
export async function rememberRecipient(
  userId: string,
  channel: Channel,
  recipient: string,
): Promise<void> {
  if (!isRecipientKey(channel, recipient)) {
    throw new Error(`not a ${channel} recipient key: refusing to remember it`);
  }
  const current = await readRememberedRecipients(userId);
  if (current[channel] === recipient) return;
  await writeRecipients(userId, { ...current, [channel]: recipient });
}

/** Forgets the channel's recipient; the cookie goes when nothing is left. Server actions only. */
export async function forgetRecipient(userId: string, channel: Channel): Promise<void> {
  const current = await readRememberedRecipients(userId);
  if (current[channel] === undefined) return;
  const rest = Object.fromEntries(
    Object.entries(current).filter(([name]) => name !== channel),
  ) as RememberedRecipients;
  await writeRecipients(userId, rest);
}

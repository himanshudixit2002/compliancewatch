import type { SelectOption, Tone } from "@compliancewatch/ui";
import type { notification } from "@compliancewatch/contracts/openapi";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The digests screen's model: the people at a CA firm whom the notification service writes to
 * about their clients, and whether each hears through the daily digest (one message a day
 * covering every client) or about each change on its own. The mode is the recipient's
 * `digest_mode` on the notification service; changing it waits for
 * `PUT /v1/notification/recipients/{recipient_id}/digest`, which is not scheduled.
 */
export type DigestMode = notification.components["schemas"]["DigestMode"];

export const DIGEST_MODES: readonly DigestMode[] = ["daily", "off"];

export interface DigestRecipient {
  /** The notification service's recipient id. */
  id: string;
  name: string;
  /** Where the digest goes first: a WhatsApp number or an email address. */
  address: string;
  mode: DigestMode;
  /** How many client businesses the person hears about. */
  clientCount: number;
  /** When the person's last digest went out, an ISO instant; null before the first. */
  lastSentAt: string | null;
}

export interface DigestCounts {
  total: number;
  daily: number;
}

/** The form fields the save action reads. */
export const DIGEST_FIELDS = { recipientId: "recipient_id", mode: "mode" } as const;

export const DIGEST_MODE_LABEL: Readonly<Record<DigestMode, MessageKey>> = {
  daily: "caSettings.digests.mode.daily",
  off: "caSettings.digests.mode.off",
};

export const DIGEST_MODE_TONE: Readonly<Record<DigestMode, Tone>> = {
  daily: "info",
  off: "neutral",
};

export function digestModeOptions(): SelectOption[] {
  return DIGEST_MODES.map((mode) => ({ value: mode, label: t(DIGEST_MODE_LABEL[mode]) }));
}

/** By name, so a person is easy to find. */
export function sortRecipients(recipients: readonly DigestRecipient[]): DigestRecipient[] {
  return [...recipients].sort((a, b) => a.name.localeCompare(b.name));
}

export function digestCounts(recipients: readonly DigestRecipient[]): DigestCounts {
  return {
    total: recipients.length,
    daily: recipients.filter((recipient) => recipient.mode === "daily").length,
  };
}

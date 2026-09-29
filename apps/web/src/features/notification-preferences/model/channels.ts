import type { ConsentPurpose } from "@/entities/consent/types";
import { emailKeyOf, whatsappKeyOf } from "@/entities/notification/mappers";
import type { Channel } from "@/entities/notification/types";
import { t } from "@/shared/i18n";
import { isE164, isEmailAddress, normalisePhone } from "@/shared/lib/identifiers";

/**
 * The channels a reminder preference is kept for and what each one needs. A preference is
 * keyed by channel and recipient on the notification service (a WhatsApp number as digits
 * without the plus, an address lowercased) and belongs to no tenant. Opting a recipient in is
 * backed by the user's consent to that channel's reminders (docs/legal/whatsapp-consent.md:
 * the consent is recorded, then the preference is set), so each channel names its purpose.
 */
export const CHANNEL_PURPOSE: Readonly<Record<Channel, ConsentPurpose>> = {
  whatsapp: "whatsapp_reminders",
  email: "email_reminders",
};

export function channelLabel(channel: Channel): string {
  return t(`notifications.channel.${channel}`);
}

/** The field's label: "WhatsApp number", "Email address". */
export function recipientFieldLabel(channel: Channel): string {
  return t(`notifications.recipient.${channel}`);
}

export type ParsedRecipient = { ok: true; key: string } | { ok: false; error: string };

/** A typed number or address as the service's key, or why it is not one. */
export function parseRecipient(channel: Channel, raw: string): ParsedRecipient {
  if (channel === "whatsapp") {
    const number = normalisePhone(raw);
    if (number === "") return { ok: false, error: t("consent.error.whatsappNumberMissing") };
    if (!isE164(number)) return { ok: false, error: t("consent.error.whatsappNumber") };
    return { ok: true, key: whatsappKeyOf(number) };
  }
  const address = emailKeyOf(raw);
  if (address === "") return { ok: false, error: t("notifications.error.emailMissing") };
  if (!isEmailAddress(address)) return { ok: false, error: t("notifications.error.email") };
  return { ok: true, key: address };
}

import type { notification } from "@compliancewatch/contracts/openapi";
import type { Channel } from "@/entities/notification/types";
import type { MessageKey } from "@/shared/i18n";

/**
 * The notification recipients screen's model: who the notification service sends reminders
 * to, as `GET /v1/notification/recipients` returns them. A recipient speaks for an
 * organisation in a role, has addresses tried in order, is linked to businesses, and may have
 * its notifications held for the daily digest.
 */
type Schemas = notification.components["schemas"];

export type RecipientDto = Schemas["RecipientOut"];
export type RecipientRole = Schemas["RecipientRole"];

export interface RecipientAddress {
  channel: Channel;
  address: string;
}

export interface Recipient {
  id: string;
  orgLabel: string;
  role: RecipientRole;
  /** Two letters, such as "en". */
  language: string;
  /** In the order the service tries them. */
  addresses: readonly RecipientAddress[];
  /** The labels of the businesses the recipient hears about. */
  businesses: readonly string[];
  /** Notifications wait for the daily digest (chosen, or a CA firm's recipient). */
  byDigest: boolean;
  /** An ISO instant. */
  updatedAt: string;
}

export interface RecipientSummary {
  total: number;
  whatsapp: number;
  email: number;
  byDigest: number;
}

export const ROLE_LABEL: Readonly<Record<RecipientRole, MessageKey>> = {
  owner: "role.owner",
  staff: "role.staff",
  ca_admin: "role.ca_admin",
  ca_staff: "role.ca_staff",
};

export const CHANNEL_LABEL: Readonly<Record<Channel, MessageKey>> = {
  whatsapp: "notifications.channel.whatsapp",
  email: "notifications.channel.email",
};

export function recipientFromDto(dto: RecipientDto): Recipient {
  return {
    id: dto.id,
    orgLabel: dto.org_label,
    role: dto.role,
    language: dto.language,
    addresses: [...dto.addresses]
      .sort((a, b) => a.position - b.position)
      .map(({ channel, address }) => ({ channel, address })),
    businesses: dto.businesses.map((business) => business.label),
    byDigest: dto.by_digest,
    updatedAt: dto.updated_at,
  };
}

/** Recipients by organisation, unnamed ones last. */
export function sortRecipients(recipients: readonly Recipient[]): Recipient[] {
  return [...recipients].sort((a, b) => {
    if (a.orgLabel === "" || b.orgLabel === "") return a.orgLabel === "" ? 1 : -1;
    return a.orgLabel.localeCompare(b.orgLabel);
  });
}

function reaches(recipient: Recipient, channel: Channel): boolean {
  return recipient.addresses.some((address) => address.channel === channel);
}

/** The counts for the summary row: recipients, those with a WhatsApp or email address, digests. */
export function recipientSummary(recipients: readonly Recipient[]): RecipientSummary {
  return {
    total: recipients.length,
    whatsapp: recipients.filter((recipient) => reaches(recipient, "whatsapp")).length,
    email: recipients.filter((recipient) => reaches(recipient, "email")).length,
    byDigest: recipients.filter((recipient) => recipient.byDigest).length,
  };
}

const languageNames = new Intl.DisplayNames(["en"], { type: "language", fallback: "none" });

/** "hi" to "Hindi", from the platform's language names; the code itself when it has none. */
export function languageName(code: string): string {
  try {
    return languageNames.of(code) ?? code;
  } catch {
    return code;
  }
}

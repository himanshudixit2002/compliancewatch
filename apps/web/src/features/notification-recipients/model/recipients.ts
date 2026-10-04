import type { Channel, DigestMode, Recipient, RecipientRole } from "@/entities/notification/types";
import type { TenantKind } from "@/shared/config/roles";
import type { MessageKey } from "@/shared/i18n";

/**
 * The notification recipients screen's model: who the notification service sends a business's
 * reminders to, as `GET /v1/notification/recipients?business_id=` returns them. A recipient
 * speaks for an organisation in a role, has addresses tried in order, follows one or more
 * businesses, and may have its notifications held for the daily digest (always, for a CA firm's
 * people).
 */
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

export const DIGEST_LABEL: Readonly<Record<DigestMode, MessageKey>> = {
  off: "recipients.delivery.immediate",
  daily: "recipients.delivery.digest",
};

export const DIGEST_MODES: readonly DigestMode[] = ["off", "daily"];

/** The roles a recipient of the tenant may have: a business's own people, or a CA firm's. */
const ROLES_BY_KIND: Readonly<Record<TenantKind, readonly RecipientRole[]>> = {
  business: ["owner", "staff"],
  ca_firm: ["ca_admin", "ca_staff"],
  internal: [],
};

export function rolesFor(kind: TenantKind): readonly RecipientRole[] {
  return ROLES_BY_KIND[kind];
}

export interface RecipientSummary {
  total: number;
  whatsapp: number;
  email: number;
  byDigest: number;
}

/** Recipients by organisation, unnamed ones last, then by when they were added. */
export function sortRecipients(recipients: readonly Recipient[]): Recipient[] {
  return [...recipients].sort((a, b) => {
    if (a.orgLabel === "" && b.orgLabel !== "") return 1;
    if (b.orgLabel === "" && a.orgLabel !== "") return -1;
    return a.orgLabel.localeCompare(b.orgLabel) || a.createdAt.localeCompare(b.createdAt);
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

import { isE164, isEmailAddress } from "@/shared/lib/identifiers";
import type {
  BulkNotificationInDto,
  BulkNotificationOutDto,
  BulkNotificationResult,
  Channel,
  DeliveryState,
  MessageTemplate,
  NotificationDto,
  NotificationPage,
  NotificationPageDto,
  NotificationRecord,
  Preference,
  PreferenceChange,
  PreferenceDto,
  PreferenceInDto,
  Recipient,
  RecipientDto,
  RecipientInDto,
  RecipientInput,
  RecipientPage,
  RecipientPageDto,
  Template,
  TemplateDto,
} from "./types";

/** The channels a preference is kept for, in the order the settings page shows them. */
export const CHANNELS: readonly Channel[] = ["whatsapp", "email"];

export function isChannel(value: string): value is Channel {
  return (CHANNELS as readonly string[]).includes(value);
}

/**
 * How a recipient is keyed on the notification service. WhatsApp reports a number as its
 * digits without the plus (the bot's opt-ins and the seed use that form), so a WhatsApp
 * preference is keyed that way; an email address is keyed lowercased.
 */
const WHATSAPP_KEY = /^[1-9][0-9]{7,14}$/;

/** "+919800000001" -> "919800000001"; throws for a value that is not E.164. */
export function whatsappKeyOf(e164: string): string {
  if (!isE164(e164)) throw new Error("not an E.164 number");
  return e164.slice(1);
}

/** "919800000001" -> "+919800000001", for a field or a sentence. */
export function whatsappNumberOf(key: string): string {
  return `+${key}`;
}

export function emailKeyOf(address: string): string {
  return address.trim().toLowerCase();
}

/** True when the value is a key the service uses for the channel. */
export function isRecipientKey(channel: Channel, value: string): boolean {
  if (channel === "whatsapp") return WHATSAPP_KEY.test(value);
  return isEmailAddress(value) && value === emailKeyOf(value);
}

/** The recipient as a person reads it: the number with its plus, or the address. */
export function recipientLabel(channel: Channel, key: string): string {
  return channel === "whatsapp" ? whatsappNumberOf(key) : key;
}

export function preferenceFromDto(dto: PreferenceDto): Preference {
  return {
    channel: dto.channel,
    recipient: dto.recipient,
    optedIn: dto.opted_in,
    source: dto.source,
    language: dto.language,
    quietHoursStart: dto.quiet_hours_start,
    quietHoursEnd: dto.quiet_hours_end,
    updatedAt: dto.updated_at,
  };
}

/** The PUT body; the language and the quiet hours travel only when set. */
export function preferenceChangeToDto(change: PreferenceChange): PreferenceInDto {
  const dto: PreferenceInDto = { opted_in: change.optedIn, source: change.source };
  if (change.language !== undefined) dto.language = change.language;
  if (change.quietHoursStart !== undefined) dto.quiet_hours_start = change.quietHoursStart;
  if (change.quietHoursEnd !== undefined) dto.quiet_hours_end = change.quietHoursEnd;
  if (change.subject !== undefined) dto.subject = change.subject;
  return dto;
}

export function templateFromDto(dto: TemplateDto): Template {
  return { key: dto.key, channel: dto.channel, language: dto.language, status: dto.status };
}

export function messageTemplateFromDto(dto: TemplateDto): MessageTemplate {
  return {
    ...templateFromDto(dto),
    metaName: dto.meta_name,
    placeholders: [...dto.placeholders],
    body: dto.body,
  };
}

export function recipientFromDto(dto: RecipientDto): Recipient {
  return {
    id: dto.id,
    userId: dto.user_id ?? null,
    role: dto.role,
    language: dto.language,
    digestMode: dto.digest_mode,
    byDigest: dto.by_digest,
    orgLabel: dto.org_label,
    addresses: [...dto.addresses]
      .sort((a, b) => a.position - b.position)
      .map(({ channel, address }) => ({ channel, address })),
    businesses: dto.businesses.map((link) => ({ businessId: link.business_id, label: link.label })),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

export function recipientPageFromDto(dto: RecipientPageDto): RecipientPage {
  return { items: dto.items.map(recipientFromDto), nextCursor: dto.next_cursor ?? null };
}

/** The PUT body: everything, in the order the addresses are to be tried. */
export function recipientInputToDto(input: RecipientInput): RecipientInDto {
  return {
    role: input.role,
    user_id: input.userId,
    language: input.language,
    digest_mode: input.digestMode,
    org_label: input.orgLabel,
    addresses: input.addresses.map(({ channel, address }) => ({ channel, address })),
    businesses: input.businesses.map((link) => ({
      business_id: link.businessId,
      label: link.label,
    })),
  };
}

/** The delivery states, in the order a notification moves through them, then the dead ends. */
export const DELIVERY_STATES: readonly DeliveryState[] = [
  "queued",
  "digest_pending",
  "sent",
  "delivered",
  "read",
  "failed",
  "suppressed",
];

export function isDeliveryState(value: string): value is DeliveryState {
  return (DELIVERY_STATES as readonly string[]).includes(value);
}

export function notificationFromDto(dto: NotificationDto): NotificationRecord {
  return {
    id: dto.id,
    businessId: dto.business_id,
    obligationId: dto.obligation_id,
    recipientId: dto.recipient_id ?? null,
    channel: dto.channel,
    address: dto.address,
    occasion: dto.occasion,
    templateKey: dto.template_key,
    language: dto.language,
    params: { ...dto.params },
    state: dto.state,
    attempts: dto.attempts,
    availableAt: dto.available_at,
    dispatchId: dto.dispatch_id ?? null,
    providerMessageId: dto.provider_message_id,
    error: dto.error,
    fallbackOf: dto.fallback_of ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    sentAt: dto.sent_at ?? null,
    deliveredAt: dto.delivered_at ?? null,
    readAt: dto.read_at ?? null,
    failedAt: dto.failed_at ?? null,
  };
}

export function notificationPageFromDto(dto: NotificationPageDto): NotificationPage {
  return { items: dto.items.map(notificationFromDto), nextCursor: dto.next_cursor ?? null };
}

/** The change card for the businesses named, each once, in the order given. */
export function bulkRequestToDto(
  ruleVersionId: string,
  businessIds: readonly string[],
): BulkNotificationInDto {
  return {
    rule_version_id: ruleVersionId,
    business_ids: [...new Set(businessIds)],
    kind: "change_card",
  };
}

export function bulkResultFromDto(dto: BulkNotificationOutDto): BulkNotificationResult {
  return {
    ruleVersionId: dto.rule_version_id,
    queued: dto.queued,
    skippedDuplicate: dto.skipped_duplicate,
    skippedNoRecipient: dto.skipped_no_recipient,
    skippedNotAffected: dto.skipped_not_affected,
    notificationsQueued: dto.notifications_queued,
    businesses: dto.businesses.map((business) => ({
      businessId: business.business_id,
      outcome: business.outcome,
      obligationId: business.obligation_id ?? null,
      queued: business.queued,
      duplicates: business.duplicates,
      unreachable: business.unreachable,
    })),
  };
}

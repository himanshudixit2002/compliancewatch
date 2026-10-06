import type { notification } from "@compliancewatch/contracts/openapi";

/**
 * A notification preference: whether a recipient (an E.164 number on WhatsApp, an address on
 * email) is opted in on a channel, in which language, and the quiet hours in IST during which
 * reminders are held. The notification service keeps one per channel and recipient; a PUT
 * replaces it. It belongs to no tenant.
 */
type Schemas = notification.components["schemas"];

export type PreferenceDto = Schemas["PreferenceOut"];
export type PreferenceInDto = Schemas["PreferenceIn"];
export type TemplateDto = Schemas["TemplateOut"];

export type Channel = Schemas["Channel"];
export type PreferenceSource = Schemas["ConsentSource"];

export interface Preference {
  channel: Channel;
  recipient: string;
  optedIn: boolean;
  source: PreferenceSource;
  language: string;
  /** HH:MM in IST. */
  quietHoursStart: string;
  quietHoursEnd: string;
  updatedAt: string;
}

export interface PreferenceChange {
  optedIn: boolean;
  source: PreferenceSource;
  /** Two letters; the service keeps its default when absent. */
  language?: string;
  quietHoursStart?: string;
  quietHoursEnd?: string;
}

/**
 * A message template as the settings page needs it: which languages a channel has templates in.
 * The body and placeholders stay on the service; `status` is Meta's approval state as recorded.
 */
export interface Template {
  key: string;
  channel: Channel;
  language: string;
  status: string;
}

/**
 * A message template as the template console shows it: the text with its `{placeholders}`, the
 * name it carries at Meta and its approval status there. The text holds placeholders only; the
 * facts a message carries come from the rulebook and the obligation when it is sent.
 */
export interface MessageTemplate extends Template {
  metaName: string;
  placeholders: readonly string[];
  body: string;
}

/**
 * A recipient of a tenant's reminders: someone the notification service sends to about one or
 * more businesses, in a role, with addresses tried in order (a WhatsApp number as +digits, an
 * email address in lower case). Registering an address gives no consent: the service sends only
 * to an address whose preference is opted in. `PUT /v1/notification/recipients/{id}` registers a
 * recipient or replaces it whole.
 */
export type RecipientDto = Schemas["RecipientOut"];
export type RecipientPageDto = Schemas["Page_RecipientOut_"];
export type RecipientInDto = Schemas["RecipientIn"];
export type RecipientRole = Schemas["RecipientRole"];
export type DigestMode = Schemas["DigestMode"];

export interface RecipientAddress {
  channel: Channel;
  address: string;
}

export interface BusinessLink {
  businessId: string;
  /** What the recipient calls the business; the messages name the business with it. */
  label: string;
}

export interface Recipient {
  id: string;
  /** The person's user id when they sign in to the web app. */
  userId: string | null;
  role: RecipientRole;
  /** Two letters, such as "en". */
  language: string;
  digestMode: DigestMode;
  /** Notifications wait for the daily digest: chosen, or the recipient is a CA firm's. */
  byDigest: boolean;
  /** The organisation the recipient speaks for, such as a CA firm's name; may be empty. */
  orgLabel: string;
  /** In the order the service tries them. */
  addresses: readonly RecipientAddress[];
  businesses: readonly BusinessLink[];
  createdAt: string;
  updatedAt: string;
}

export interface RecipientPage {
  items: readonly Recipient[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

/** What a PUT sends: the whole recipient, since the service replaces it. */
export interface RecipientInput {
  role: RecipientRole;
  userId: string | null;
  language: string;
  digestMode: DigestMode;
  orgLabel: string;
  addresses: readonly RecipientAddress[];
  businesses: readonly BusinessLink[];
}

/**
 * A notification as the notification service records it (`NotificationOut`): to whom (a channel
 * and a normalised address, the recipient when it came from one), about what (the business, the
 * obligation, the occasion and the template with its language and the values it was filled
 * with), and how far it got (its delivery state, the attempts, the times it was sent, delivered,
 * read or failed, the channel's last error). The service keeps no subject or body: the message is
 * rendered from the template when it goes out and not stored.
 */
export type NotificationDto = Schemas["NotificationOut"];
export type NotificationPageDto = Schemas["Page_NotificationOut_"];
export type DeliveryState = Schemas["DeliveryState"];
export type OccasionKind = Schemas["OccasionKind"];

export interface NotificationRecord {
  id: string;
  businessId: string;
  obligationId: string;
  /** Null for a send addressed straight to a number. */
  recipientId: string | null;
  channel: Channel;
  /** +digits for WhatsApp, lower case for email. */
  address: string;
  occasion: OccasionKind;
  templateKey: string;
  language: string;
  /** The values the message was filled with; emptied 30 days after the notification ended. */
  params: Readonly<Record<string, unknown>>;
  state: DeliveryState;
  attempts: number;
  /** When it may go out, or when it is tried again. */
  availableAt: string;
  dispatchId: string | null;
  /** Empty until the provider took it. */
  providerMessageId: string;
  /** The channel's last error; empty when there was none. */
  error: string;
  /** The notification this one falls back from, on another channel. */
  fallbackOf: string | null;
  createdAt: string;
  updatedAt: string;
  sentAt: string | null;
  deliveredAt: string | null;
  readAt: string | null;
  failedAt: string | null;
}

export interface NotificationPage {
  items: readonly NotificationRecord[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

/**
 * A CA firm's bulk change card (`POST /v1/notification/bulk`): one change and the client
 * businesses it affects, each told once per person who follows it. The answer says what became of
 * each business, in the order the request named them: its card queued for its client recipients,
 * already sent to them (`duplicate`), nobody to tell (`no_recipient`), or no open obligation of
 * the change (`not_affected`, which another tenant's business reads as too).
 */
export type BulkNotificationInDto = Schemas["BulkNotificationIn"];
export type BulkNotificationOutDto = Schemas["BulkNotificationOut"];
export type BulkOutcome = Schemas["BulkOutcome"];

export interface BulkBusinessResult {
  businessId: string;
  outcome: BulkOutcome;
  /** The obligation the card is about; null when not affected. */
  obligationId: string | null;
  /** Client recipients told now, those who had it already, and those with no open address. */
  queued: number;
  duplicates: number;
  unreachable: number;
}

export interface BulkNotificationResult {
  ruleVersionId: string;
  /** Businesses whose card was queued for at least one person. */
  queued: number;
  skippedDuplicate: number;
  skippedNoRecipient: number;
  skippedNotAffected: number;
  /** Change cards queued, one per person. */
  notificationsQueued: number;
  businesses: readonly BulkBusinessResult[];
}

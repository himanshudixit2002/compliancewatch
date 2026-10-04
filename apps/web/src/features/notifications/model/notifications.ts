import type { Tone } from "@compliancewatch/ui";
import { DELIVERY_STATES, isDeliveryState } from "@/entities/notification/mappers";
import type {
  Channel,
  DeliveryState,
  NotificationRecord,
  OccasionKind,
} from "@/entities/notification/types";
import { t, type MessageKey } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";
import { maskIdentifier } from "@/shared/lib/identifiers";
import { languageName } from "@/shared/lib/languages";

/**
 * The notification history as the notification service records it (`NotificationOut`): the
 * template, the channel and the address it went to, the occasion, the delivery state with its
 * attempts and times, and the channel's last error. The service keeps no subject and no body (a
 * message is rendered when it goes out and not stored), so nothing here invents one: a row is
 * named by its template. The address is shown masked wherever the history is shown, so a
 * colleague's or another tenant's number does not appear in full on a list.
 */
export { DELIVERY_STATES };
export type { DeliveryState };

/** One page of history, newest first; the service allows up to 200. */
export const HISTORY_PAGE_SIZE = 25;

const CURSOR_MAX_LENGTH = 512;

const STATE_TONE: Readonly<Record<DeliveryState, Tone>> = {
  queued: "neutral",
  digest_pending: "neutral",
  sent: "info",
  delivered: "success",
  read: "success",
  failed: "danger",
  suppressed: "warning",
};

const STATE_LABEL: Readonly<Record<DeliveryState, MessageKey>> = {
  queued: "notificationLog.state.queued",
  digest_pending: "notificationLog.state.digest_pending",
  sent: "notificationLog.state.sent",
  delivered: "notificationLog.state.delivered",
  read: "notificationLog.state.read",
  failed: "notificationLog.state.failed",
  suppressed: "notificationLog.state.suppressed",
};

const OCCASION_LABEL: Readonly<Record<OccasionKind, MessageKey>> = {
  change_card: "notificationLog.occasion.change_card",
  reminder: "notificationLog.occasion.reminder",
  closure: "notificationLog.occasion.closure",
  reschedule: "notificationLog.occasion.reschedule",
  manual: "notificationLog.occasion.manual",
};

const CHANNEL_LABEL: Readonly<Record<Channel, MessageKey>> = {
  whatsapp: "notificationLog.channel.whatsapp",
  email: "notificationLog.channel.email",
};

/** The tone that reinforces a delivery state's label. */
export function deliveryTone(state: DeliveryState): Tone {
  return STATE_TONE[state];
}

export function deliveryLabel(state: DeliveryState): string {
  return t(STATE_LABEL[state]);
}

export function occasionLabel(occasion: OccasionKind): string {
  return t(OCCASION_LABEL[occasion]);
}

export function channelLabel(channel: Channel): string {
  return t(CHANNEL_LABEL[channel]);
}

/** A row's name: its template in words ("opt_in_confirmed" is "Opt in confirmed"). */
export function templateTitle(templateKey: string): string {
  return humanise(templateKey);
}

/**
 * The address with most of it hidden: the last four digits of a number, the first character of
 * a mailbox with its domain. Enough to tell two of one's own addresses apart, not to copy one.
 */
export function maskAddress(channel: Channel, address: string): string {
  if (channel === "email") {
    const at = address.lastIndexOf("@");
    if (at <= 0) return maskIdentifier(address, 2);
    return `${address.charAt(0)}${"*".repeat(Math.max(at - 1, 1))}${address.slice(at)}`;
  }
  return maskIdentifier(address, 4);
}

export interface NotificationRow {
  id: string;
  href: string;
  title: string;
  templateKey: string;
  occasionLabel: string;
  channelLabel: string;
  /** The masked address. */
  to: string;
  state: DeliveryState;
  stateLabel: string;
  tone: Tone;
  attempts: number;
  createdAt: string;
  updatedAt: string;
}

export function notificationRows(
  records: readonly NotificationRecord[],
  hrefFor: (notificationId: string) => string,
): NotificationRow[] {
  return records.map((record) => ({
    id: record.id,
    href: hrefFor(record.id),
    title: templateTitle(record.templateKey),
    templateKey: record.templateKey,
    occasionLabel: occasionLabel(record.occasion),
    channelLabel: channelLabel(record.channel),
    to: maskAddress(record.channel, record.address),
    state: record.state,
    stateLabel: deliveryLabel(record.state),
    tone: deliveryTone(record.state),
    attempts: record.attempts,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
  }));
}

export interface TimeItem {
  key: string;
  label: string;
  /** An ISO instant, or null for what has not happened. */
  at: string | null;
}

export interface NotificationDetailView {
  id: string;
  businessId: string;
  title: string;
  templateKey: string;
  occasionLabel: string;
  channelLabel: string;
  to: string;
  languageLabel: string;
  state: DeliveryState;
  stateLabel: string;
  tone: Tone;
  attempts: number;
  /** The channel's last error; empty when there was none. */
  error: string;
  times: TimeItem[];
  /** The values the message was filled with, as text. */
  params: { key: string; value: string }[];
  fallbackOf: string | null;
  obligationId: string;
  recipientId: string | null;
  dispatchId: string | null;
  providerMessageId: string;
}

function paramText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function notificationDetail(record: NotificationRecord): NotificationDetailView {
  return {
    id: record.id,
    businessId: record.businessId,
    title: templateTitle(record.templateKey),
    templateKey: record.templateKey,
    occasionLabel: occasionLabel(record.occasion),
    channelLabel: channelLabel(record.channel),
    to: maskAddress(record.channel, record.address),
    languageLabel: languageName(record.language),
    state: record.state,
    stateLabel: deliveryLabel(record.state),
    tone: deliveryTone(record.state),
    attempts: record.attempts,
    error: record.error.trim(),
    times: [
      { key: "created", label: t("notificationLog.field.created"), at: record.createdAt },
      { key: "available", label: t("notificationLog.field.available"), at: record.availableAt },
      { key: "sent", label: t("notificationLog.field.sent"), at: record.sentAt },
      { key: "delivered", label: t("notificationLog.field.delivered"), at: record.deliveredAt },
      { key: "read", label: t("notificationLog.field.read"), at: record.readAt },
      { key: "failed", label: t("notificationLog.field.failed"), at: record.failedAt },
      { key: "updated", label: t("notificationLog.field.updated"), at: record.updatedAt },
    ],
    params: Object.entries(record.params)
      .map(([key, value]) => ({ key, value: paramText(value) }))
      .sort((a, b) => a.key.localeCompare(b.key)),
    fallbackOf: record.fallbackOf,
    obligationId: record.obligationId,
    recipientId: record.recipientId,
    dispatchId: record.dispatchId,
    providerMessageId: record.providerMessageId,
  };
}

/** What the history shows: one state or every state, from the cursor of an earlier page. */
export interface HistoryFilter {
  state?: DeliveryState;
  cursor?: string;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The filter from a page's query; a value the service would refuse counts as absent. */
export function readHistoryFilter(query: Query): HistoryFilter {
  const state = first(query.state);
  const cursor = first(query.cursor);
  return {
    ...(state !== undefined && isDeliveryState(state) ? { state } : {}),
    ...(cursor !== undefined && cursor !== "" && cursor.length <= CURSOR_MAX_LENGTH
      ? { cursor }
      : {}),
  };
}

export interface StateOption {
  value: string;
  label: string;
}

/** The filter's choices: every state first, then each delivery state. */
export function stateOptions(): StateOption[] {
  return [
    { value: "", label: t("notificationLog.allStates") },
    ...DELIVERY_STATES.map((state) => ({ value: state, label: deliveryLabel(state) })),
  ];
}

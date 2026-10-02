import type { Tone } from "@compliancewatch/ui";
import type { Channel } from "@/entities/notification/types";
import type { MessageKey } from "@/shared/i18n";

/**
 * The notifications a business was sent, as the notification service records them: to whom,
 * on which channel, and how far delivery got. Instants are ISO strings; the views format them
 * in IST.
 */
export type DeliveryState =
  "queued" | "digest_pending" | "sent" | "delivered" | "read" | "failed" | "suppressed";

/** Where a delivery state sits for the summary figures. */
export type DeliveryBucket = "pending" | "delivered" | "failed";

/** One row of the notifications list. */
export interface NotificationSummary {
  id: string;
  subject: string;
  channel: Channel;
  state: DeliveryState;
  /** A +<digits> number for WhatsApp, an address for email. */
  recipient: string;
  templateKey: string;
  /** Null until the notification has gone out. */
  sentAt: string | null;
}

/** One notification with its message and delivery record, for the detail screen. */
export interface NotificationRecord extends NotificationSummary {
  body: string;
  businessName: string | null;
  attempts: number;
  deliveredAt: string | null;
  readAt: string | null;
  /** The provider's last error; null when delivery did not fail. */
  error: string | null;
}

export interface NotificationCounts {
  total: number;
  pending: number;
  delivered: number;
  failed: number;
}

export const DELIVERY_STATES: readonly DeliveryState[] = [
  "queued",
  "digest_pending",
  "sent",
  "delivered",
  "read",
  "failed",
  "suppressed",
];

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

const STATE_BUCKET: Readonly<Record<DeliveryState, DeliveryBucket>> = {
  queued: "pending",
  digest_pending: "pending",
  sent: "pending",
  delivered: "delivered",
  read: "delivered",
  failed: "failed",
  suppressed: "failed",
};

const CHANNEL_LABEL: Readonly<Record<Channel, MessageKey>> = {
  whatsapp: "notificationLog.channel.whatsapp",
  email: "notificationLog.channel.email",
};

/** The tone that reinforces a delivery state's label. */
export function deliveryTone(state: DeliveryState): Tone {
  return STATE_TONE[state];
}

/** The message key naming a delivery state. */
export function deliveryLabelKey(state: DeliveryState): MessageKey {
  return STATE_LABEL[state];
}

/** Pending until the provider confirms delivery; failed when it failed or was suppressed. */
export function deliveryBucket(state: DeliveryState): DeliveryBucket {
  return STATE_BUCKET[state];
}

/** The message key naming a channel. */
export function channelLabelKey(channel: Channel): MessageKey {
  return CHANNEL_LABEL[channel];
}

/** The summary figures over a list: everything, then each delivery bucket. */
export function notificationCounts(items: readonly NotificationSummary[]): NotificationCounts {
  const counts: NotificationCounts = { total: items.length, pending: 0, delivered: 0, failed: 0 };
  for (const item of items) counts[deliveryBucket(item.state)] += 1;
  return counts;
}

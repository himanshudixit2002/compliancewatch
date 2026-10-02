import type { Tone } from "@compliancewatch/ui";
import type { Channel } from "@/entities/notification/types";
import type { MessageKey } from "@/shared/i18n";

/**
 * The internal notifications console: whether each channel is connected and within its quota,
 * the digest schedules, and the latest dispatches with how far each got. Instants are ISO
 * strings; the views format them in IST.
 */
export type DeliveryState =
  "queued" | "digest_pending" | "sent" | "delivered" | "read" | "failed" | "suppressed";

export type DeliveryBucket = "pending" | "delivered" | "failed";

/** What a notification was sent for. */
export type OccasionKind = "change_card" | "reminder" | "closure" | "reschedule" | "manual";

export type DigestMode = "off" | "daily";

export interface ChannelHealth {
  channel: Channel;
  connected: boolean;
  sentToday: number;
  /** The provider's daily sending limit; null when it sets none. */
  dailyQuota: number | null;
  lastSentAt: string | null;
}

export interface DigestSchedule {
  id: string;
  label: string;
  mode: DigestMode;
  recipientCount: number;
  lastSentAt: string | null;
}

export interface DispatchEntry {
  id: string;
  occasion: OccasionKind;
  channel: Channel;
  recipient: string;
  state: DeliveryState;
  createdAt: string;
}

export interface AdminNotificationsData {
  channels: readonly ChannelHealth[];
  digests: readonly DigestSchedule[];
  dispatchLog: readonly DispatchEntry[];
}

export interface DispatchSummary {
  total: number;
  delivered: number;
  failed: number;
  /** Delivered as a whole percentage of the dispatches that settled; null when none has. */
  deliveryRate: number | null;
}

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
  queued: "adminNotifications.state.queued",
  digest_pending: "adminNotifications.state.digest_pending",
  sent: "adminNotifications.state.sent",
  delivered: "adminNotifications.state.delivered",
  read: "adminNotifications.state.read",
  failed: "adminNotifications.state.failed",
  suppressed: "adminNotifications.state.suppressed",
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

const OCCASION_LABEL: Readonly<Record<OccasionKind, MessageKey>> = {
  change_card: "adminNotifications.occasion.change_card",
  reminder: "adminNotifications.occasion.reminder",
  closure: "adminNotifications.occasion.closure",
  reschedule: "adminNotifications.occasion.reschedule",
  manual: "adminNotifications.occasion.manual",
};

const CHANNEL_LABEL: Readonly<Record<Channel, MessageKey>> = {
  whatsapp: "adminNotifications.channel.whatsapp",
  email: "adminNotifications.channel.email",
};

const DIGEST_LABEL: Readonly<Record<DigestMode, MessageKey>> = {
  off: "adminNotifications.digest.off",
  daily: "adminNotifications.digest.daily",
};

export function stateTone(state: DeliveryState): Tone {
  return STATE_TONE[state];
}

export function stateLabelKey(state: DeliveryState): MessageKey {
  return STATE_LABEL[state];
}

/** Pending until the provider confirms delivery; failed when it failed or was suppressed. */
export function stateBucket(state: DeliveryState): DeliveryBucket {
  return STATE_BUCKET[state];
}

export function occasionLabelKey(occasion: OccasionKind): MessageKey {
  return OCCASION_LABEL[occasion];
}

export function channelLabelKey(channel: Channel): MessageKey {
  return CHANNEL_LABEL[channel];
}

export function digestModeKey(mode: DigestMode): MessageKey {
  return DIGEST_LABEL[mode];
}

/** The figures over the dispatch log; pending dispatches do not count towards the rate. */
export function dispatchSummary(entries: readonly DispatchEntry[]): DispatchSummary {
  let delivered = 0;
  let failed = 0;
  for (const entry of entries) {
    const bucket = stateBucket(entry.state);
    if (bucket === "delivered") delivered += 1;
    if (bucket === "failed") failed += 1;
  }
  const settled = delivered + failed;
  return {
    total: entries.length,
    delivered,
    failed,
    deliveryRate: settled === 0 ? null : Math.round((delivered / settled) * 100),
  };
}

export function connectedCount(channels: readonly ChannelHealth[]): number {
  return channels.filter((channel) => channel.connected).length;
}

export function activeDigestCount(digests: readonly DigestSchedule[]): number {
  return digests.filter((digest) => digest.mode !== "off").length;
}

import type { ChannelKind, NotificationKind } from "@/entities/notification/types";
import { t } from "@/shared/i18n";

export interface AdminNotificationsView {
  channels: ChannelConfig[];
  digests: DigestConfig[];
  dispatchLog: DispatchEntry[];
  recentBroadcasts: BroadcastEntry[];
  totalNotifications: number;
  deliveryRate: number;
}

export interface ChannelConfig {
  kind: ChannelKind;
  label: string;
  enabled: boolean;
  quotaUsed: number;
  quotaLimit: number;
  lastUsed: string;
}

export interface DigestConfig {
  id: string;
  kind: NotificationKind;
  label: string;
  frequency: string;
  enabled: boolean;
  recipientCount: number;
  lastSent: string;
}

export interface DispatchEntry {
  id: string;
  notificationId: string;
  kind: NotificationKind;
  channel: ChannelKind;
  recipient: string;
  status: "sent" | "delivered" | "opened" | "bounced" | "failed";
  sentAt: string;
  deliveredAt: string | null;
}

export interface BroadcastEntry {
  id: string;
  subject: string;
  kind: NotificationKind;
  channel: ChannelKind;
  recipientCount: number;
  sentAt: string;
  status: string;
}

export function emptyAdminNotifications(): AdminNotificationsView {
  return {
    channels: [],
    digests: [],
    dispatchLog: [],
    recentBroadcasts: [],
    totalNotifications: 0,
    deliveryRate: 0,
  };
}

export function channelLabel(kind: ChannelKind): string {
  return t(`notification.channel.${kind}`);
}

export function channelStatusLabel(status: string): string {
  return t(`notification.status.${status}`);
}

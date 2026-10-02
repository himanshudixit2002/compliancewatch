import type { Tone } from "@compliancewatch/ui";
import type { Channel } from "@/entities/notification/types";
import type { MessageKey } from "@/shared/i18n";

/**
 * A reminder the notification service holds for a business: what it is about, when it is due
 * and whether it has gone out or been acknowledged. `dueAt` is an ISO instant.
 */
export type ReminderStatus = "upcoming" | "sent" | "acknowledged" | "overdue";

export interface Reminder {
  id: string;
  title: string;
  description: string | null;
  dueAt: string;
  status: ReminderStatus;
  channel: Channel;
  /** The obligation the reminder is for, when it is tied to one. */
  obligationId: string | null;
}

const STATUS_TONE: Readonly<Record<ReminderStatus, Tone>> = {
  upcoming: "info",
  sent: "neutral",
  acknowledged: "success",
  overdue: "danger",
};

const STATUS_LABEL: Readonly<Record<ReminderStatus, MessageKey>> = {
  upcoming: "reminders.status.upcoming",
  sent: "reminders.status.sent",
  acknowledged: "reminders.status.acknowledged",
  overdue: "reminders.status.overdue",
};

const CHANNEL_LABEL: Readonly<Record<Channel, MessageKey>> = {
  whatsapp: "reminders.channel.whatsapp",
  email: "reminders.channel.email",
};

export function reminderTone(status: ReminderStatus): Tone {
  return STATUS_TONE[status];
}

export function reminderStatusKey(status: ReminderStatus): MessageKey {
  return STATUS_LABEL[status];
}

export function reminderChannelKey(channel: Channel): MessageKey {
  return CHANNEL_LABEL[channel];
}

/** The reminders earliest due first; reminders due at the same instant keep their order. */
export function byDueDate(items: readonly Reminder[]): Reminder[] {
  return [...items].sort((a, b) => Date.parse(a.dueAt) - Date.parse(b.dueAt));
}

/** How many reminders are overdue, for the warning above the timeline. */
export function overdueCount(items: readonly Reminder[]): number {
  return items.filter((item) => item.status === "overdue").length;
}

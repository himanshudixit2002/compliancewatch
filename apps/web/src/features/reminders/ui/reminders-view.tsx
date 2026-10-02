"use client";

import { Badge, EmptyState, PageHeader, StatusChip, Timeline } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { Tone } from "@compliancewatch/ui";
import type { ReminderView } from "../model/reminders";

export interface RemindersViewProps {
  title: string;
  items: readonly ReminderView[];
}

const STATUS_TONE: Record<ReminderView["status"], Tone> = {
  upcoming: "info",
  sent: "neutral",
  acknowledged: "success",
  overdue: "danger",
};

/** Timeline-style reminders: upcoming, sent, acknowledged or overdue. */
export function RemindersView({ title, items }: RemindersViewProps) {
  return (
    <div data-slot="reminders" className="flex flex-col gap-6">
      <PageHeader title={title} description={t("reminders.intro")} />
      {items.length === 0 ? (
        <EmptyState title={t("reminders.emptyTitle")} description={t("reminders.emptyBody")} />
      ) : (
        <Timeline
          events={items.map((item) => ({
            id: item.id,
            label: item.dueAt,
            dateTime: new Date(item.dueAt).toISOString(),
            title: item.title,
            body: (
              <div className="flex flex-wrap items-center gap-2">
                <StatusChip status={item.status} tone={STATUS_TONE[item.status]} />
                <Badge tone="neutral">{t(`notifications.channel.${item.channel}`)}</Badge>
                {item.description ? (
                  <span className="text-fg-muted">{item.description}</span>
                ) : null}
              </div>
            ),
            tone: STATUS_TONE[item.status],
          }))}
        />
      )}
    </div>
  );
}

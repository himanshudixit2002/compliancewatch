import type { Route } from "next";
import Link from "next/link";
import { Badge, Banner, EmptyState, PageHeader, StatusChip, Timeline } from "@compliancewatch/ui";
import type { TimelineEvent } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import {
  byDueDate,
  overdueCount,
  reminderChannelKey,
  reminderStatusKey,
  reminderTone,
} from "../model/reminders";
import type { Reminder } from "../model/reminders";

export interface RemindersViewProps {
  items: readonly Reminder[];
  /** The obligation a reminder is for; without it the timeline shows no obligation links. */
  obligationHref?: (obligationId: string) => Route;
}

function toEvent(item: Reminder, obligationHref?: (id: string) => Route): TimelineEvent {
  const tone = reminderTone(item.status);
  return {
    id: item.id,
    label: formatDateTime(item.dueAt),
    dateTime: item.dueAt,
    title: item.title,
    tone,
    body: (
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={item.status} tone={tone} label={t(reminderStatusKey(item.status))} />
          <Badge tone="neutral">{t(reminderChannelKey(item.channel))}</Badge>
          {item.obligationId !== null && obligationHref !== undefined ? (
            <Link
              href={obligationHref(item.obligationId)}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("reminders.toObligation")}
            </Link>
          ) : null}
        </div>
        {item.description ? <p>{item.description}</p> : null}
      </div>
    ),
  };
}

/** A business's reminders on a timeline, earliest due first, with overdue ones called out. */
export function RemindersView({ items, obligationHref }: RemindersViewProps) {
  const overdue = overdueCount(items);
  return (
    <div data-slot="reminders" className="flex flex-col gap-6">
      <PageHeader title={t("reminders.title")} description={t("reminders.intro")} />
      {overdue > 0 ? (
        <Banner tone="warning" title={t("reminders.overdueTitle", { count: overdue })}>
          {t("reminders.overdueBody")}
        </Banner>
      ) : null}
      {items.length === 0 ? (
        <EmptyState title={t("reminders.emptyTitle")} body={t("reminders.emptyBody")} />
      ) : (
        <Timeline
          aria-label={t("reminders.timelineLabel")}
          events={byDueDate(items).map((item) => toEvent(item, obligationHref))}
        />
      )}
    </div>
  );
}

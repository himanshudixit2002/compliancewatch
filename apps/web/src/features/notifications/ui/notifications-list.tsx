import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  channelLabelKey,
  deliveryLabelKey,
  deliveryTone,
  notificationCounts,
} from "../model/notifications";
import type { NotificationSummary } from "../model/notifications";
import type { NotificationRow } from "./notification-rows";
import { NotificationsTable } from "./notifications-table";

export interface NotificationsListProps {
  items: readonly NotificationSummary[];
  /** The detail screen of one notification. */
  hrefFor: (id: string) => Route;
}

function toRow(item: NotificationSummary, hrefFor: (id: string) => Route): NotificationRow {
  return {
    id: item.id,
    subject: item.subject,
    href: hrefFor(item.id),
    channelLabel: t(channelLabelKey(item.channel)),
    state: item.state,
    stateLabel: t(deliveryLabelKey(item.state)),
    tone: deliveryTone(item.state),
    recipient: item.recipient,
    sentLabel: item.sentAt === null ? t("notificationLog.notSent") : formatDateTime(item.sentAt),
  };
}

/** The notifications sent for a business: summary figures, then a searchable table. */
export function NotificationsList({ items, hrefFor }: NotificationsListProps) {
  const counts = notificationCounts(items);
  return (
    <div data-slot="notifications-list" className="flex flex-col gap-6">
      <PageHeader title={t("notificationLog.title")} description={t("notificationLog.intro")} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={t("notificationLog.stat.total")} value={counts.total} />
        <StatCard label={t("notificationLog.stat.pending")} value={counts.pending} tone="info" />
        <StatCard
          label={t("notificationLog.stat.delivered")}
          value={counts.delivered}
          tone="success"
        />
        <StatCard
          label={t("notificationLog.stat.failed")}
          value={counts.failed}
          tone={counts.failed > 0 ? "danger" : "neutral"}
        />
      </div>
      {items.length === 0 ? (
        <EmptyState title={t("notificationLog.emptyTitle")} body={t("notificationLog.emptyBody")} />
      ) : (
        <NotificationsTable rows={items.map((item) => toRow(item, hrefFor))} />
      )}
    </div>
  );
}

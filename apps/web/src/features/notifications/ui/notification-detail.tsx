import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  KeyValue,
  PageHeader,
  StatusChip,
} from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { channelLabelKey, deliveryLabelKey, deliveryTone } from "../model/notifications";
import type { NotificationRecord } from "../model/notifications";

export interface NotificationDetailProps {
  notification: NotificationRecord;
  /** The notifications list this one was opened from. */
  listHref: Route;
}

function when(instant: string | null): string {
  return instant === null ? t("common.none") : formatDateTime(instant);
}

/** One notification: its delivery facts, the message as sent and any delivery error. */
export function NotificationDetail({ notification, listHref }: NotificationDetailProps) {
  const items: KeyValueItem[] = [
    {
      key: "state",
      label: t("notificationLog.field.state"),
      value: (
        <StatusChip
          status={notification.state}
          tone={deliveryTone(notification.state)}
          label={t(deliveryLabelKey(notification.state))}
        />
      ),
    },
    {
      key: "channel",
      label: t("notificationLog.field.channel"),
      value: t(channelLabelKey(notification.channel)),
    },
    {
      key: "recipient",
      label: t("notificationLog.field.recipient"),
      value: notification.recipient,
    },
    {
      key: "business",
      label: t("notificationLog.field.business"),
      value: notification.businessName ?? t("common.none"),
    },
    {
      key: "template",
      label: t("notificationLog.field.template"),
      value: <code className="font-mono text-xs">{notification.templateKey}</code>,
    },
    { key: "sentAt", label: t("notificationLog.field.sentAt"), value: when(notification.sentAt) },
    {
      key: "deliveredAt",
      label: t("notificationLog.field.deliveredAt"),
      value: when(notification.deliveredAt),
    },
    { key: "readAt", label: t("notificationLog.field.readAt"), value: when(notification.readAt) },
    {
      key: "attempts",
      label: t("notificationLog.field.attempts"),
      value: String(notification.attempts),
    },
    {
      key: "id",
      label: t("notificationLog.field.id"),
      value: <code className="font-mono text-xs">{notification.id}</code>,
      copy: notification.id,
    },
  ];
  return (
    <div data-slot="notification-detail" className="flex flex-col gap-6">
      <Link
        href={listHref}
        className="inline-flex w-fit items-center gap-1 text-sm text-fg-muted hover:text-fg"
      >
        <span aria-hidden="true">←</span>
        <span>{t("notificationLog.backToList")}</span>
      </Link>
      <PageHeader title={notification.subject} description={t("notificationLog.detailIntro")} />
      {notification.error === null ? null : (
        <Banner tone="danger" title={t("notificationLog.errorTitle")}>
          {notification.error}
        </Banner>
      )}
      <KeyValue items={items} aria-label={t("notificationLog.field.section")} />
      <Card data-slot="notification-body" className="gap-3">
        <CardHeader className="px-4">
          <CardTitle className="text-base font-semibold text-fg">
            {t("notificationLog.bodyTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4">
          <p className="text-sm whitespace-pre-wrap text-fg">{notification.body}</p>
        </CardContent>
      </Card>
    </div>
  );
}

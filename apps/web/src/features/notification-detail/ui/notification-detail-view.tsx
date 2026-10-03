"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Icon,
  KeyValue,
  PageHeader,
  StatusChip,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface NotificationDetailViewProps {
  id: string;
  subject: string;
  channel: string;
  state: string;
  recipient: string;
  businessName?: string;
  templateKey: string;
  sentAt: string | null;
  deliveredAt: string | null;
  readAt: string | null;
  attempts: number;
  listHref: string;
}

export function NotificationDetailView({
  id,
  subject,
  channel,
  state,
  recipient,
  businessName,
  templateKey,
  sentAt,
  deliveredAt,
  readAt,
  attempts,
  listHref,
}: NotificationDetailViewProps) {
  return (
    <div data-slot="notification-detail" className="flex max-w-3xl flex-col gap-6">
      <PageHeader
        title={subject}
        description={t("notificationLog.detail.intro")}
        actions={
          <Button variant="secondary" asChild>
            <Link href={listHref}>{t("common.backToList")}</Link>
          </Button>
        }
      />

      <Card>
        <CardContent className="p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <KeyValue
              label={t("notificationLog.field.state")}
              value={<StatusChip status={state} tone="info" label={state} />}
            />
            <KeyValue label={t("notificationLog.field.channel")} value={channel} />
            <KeyValue label={t("notificationLog.field.recipient")} value={recipient} />
            <KeyValue
              label={t("notificationLog.field.business")}
              value={businessName || t("common.none")}
            />
            <KeyValue
              label={t("notificationLog.field.template")}
              value={<code className="font-mono text-xs">{templateKey}</code>}
            />
            <KeyValue label={t("notificationLog.field.attempts")} value={String(attempts)} />
            <KeyValue
              label={t("notificationLog.field.sentAt")}
              value={sentAt || t("common.none")}
            />
            <KeyValue
              label={t("notificationLog.field.deliveredAt")}
              value={deliveredAt || t("common.none")}
            />
            <KeyValue
              label={t("notificationLog.field.readAt")}
              value={readAt || t("common.none")}
            />
            <KeyValue
              label={t("notificationLog.field.id")}
              value={<code className="font-mono text-xs">{id}</code>}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

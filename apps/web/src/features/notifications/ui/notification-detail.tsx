"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  KeyValue,
  PageHeader,
  StatusChip,
} from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import type { Route } from "next";
import { t } from "@/shared/i18n";
import { hrefFor, screenById } from "@/shared/config/screens";

export interface NotificationDetailView {
  id: string;
  subject: string;
  channel: "email" | "whatsapp";
  status: "sent" | "delivered" | "read" | "failed";
  recipient: string;
  sentAt: string;
  readAt: string | null;
  templateKey: string;
  body: string;
  tenantName: string | null;
  deliveryAttempts: number;
  errorMessage: string | null;
}

export interface NotificationDetailProps {
  view: NotificationDetailView;
  backHref: string;
}

const LIST_SCREEN = screenById("owner.notifications");

function BackLink({ href }: { href: string }) {
  return (
    <Link
      href={href as Route}
      className="inline-flex items-center gap-1 text-sm text-fg-muted hover:text-fg"
    >
      <span aria-hidden="true">←</span>
      <span>{t("common.back")}</span>
    </Link>
  );
}

function BodyCard({ subject, body }: { subject: string; body: string }) {
  return (
    <Card data-slot="notification-body" className="gap-3">
      <CardHeader className="px-4">
        <CardTitle className="text-base font-semibold text-fg">{subject}</CardTitle>
      </CardHeader>
      <CardContent className="px-4">
        <p className="whitespace-pre-wrap text-sm text-fg">{body}</p>
      </CardContent>
    </Card>
  );
}

function ErrorCard({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <Card
      data-slot="notification-error"
      className="gap-3 border-red-200 bg-red-50/50 dark:border-red-800 dark:bg-red-950/30"
    >
      <CardHeader className="px-4">
        <CardTitle className="text-base font-semibold text-red-700 dark:text-red-300">
          {t("notifications.deliveryErrorTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4">
        <p className="text-sm text-red-700 dark:text-red-300">{message}</p>
      </CardContent>
    </Card>
  );
}

/** The notification detail: subject, key facts, body and any delivery error. */
export function NotificationDetail({ view, backHref }: NotificationDetailProps) {
  const channelNode: ReactNode = (
    <Badge tone="neutral">{t(`notifications.channel.${view.channel}`)}</Badge>
  );
  const statusNode: ReactNode = <StatusChip status={view.status} />;
  const items: KeyValueItem[] = [
    {
      key: "id",
      label: t("notifications.field.id"),
      value: <code className="font-mono text-xs">{view.id}</code>,
    },
    { key: "channel", label: t("notifications.field.channel"), value: channelNode },
    { key: "status", label: t("notifications.field.status"), value: statusNode },
    { key: "recipient", label: t("notifications.field.recipient"), value: view.recipient },
    {
      key: "template",
      label: t("notifications.field.template"),
      value: <code className="font-mono text-xs">{view.templateKey}</code>,
    },
    {
      key: "tenant",
      label: t("notifications.field.tenant"),
      value: view.tenantName ?? t("common.none"),
    },
    { key: "sentAt", label: t("notifications.field.sentAt"), value: view.sentAt },
    {
      key: "readAt",
      label: t("notifications.field.readAt"),
      value: view.readAt ?? t("common.none"),
    },
    {
      key: "attempts",
      label: t("notifications.field.attempts"),
      value: String(view.deliveryAttempts),
    },
  ];
  return (
    <div data-slot="notification-detail" className="flex flex-col gap-6">
      <BackLink href={backHref} />
      <PageHeader
        title={view.subject}
        description={t("notifications.detailIntro")}
        actions={
          <Link
            href={hrefFor(LIST_SCREEN) as Route}
            className="text-sm text-fg-muted underline-offset-2 hover:text-fg hover:underline"
          >
            {t("notifications.backToList")}
          </Link>
        }
      />
      <KeyValue items={items} aria-label={t("notifications.field.section")} />
      <BodyCard subject={view.subject} body={view.body} />
      <ErrorCard message={view.errorMessage} />
    </div>
  );
}

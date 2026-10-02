"use client";

import type { ChangeEvent } from "react";
import Link from "next/link";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Route } from "next";
import { t } from "@/shared/i18n";
import { hrefFor, screenById } from "@/shared/config/screens";
import type { NotificationView } from "../model/notifications";

export interface NotificationsListProps {
  view: {
    items: readonly NotificationView[];
    counts: { total: number; sent: number; delivered: number; failed: number };
  };
  search: { value: string; onChange: (value: string) => void };
  baseHref: string;
}

const NOTIFICATION_SCREEN = screenById("owner.notifications");

function StatCards({ counts }: { counts: NotificationsListProps["view"]["counts"] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      <Card data-slot="stat-card">
        <CardHeader className="px-4 pb-2 pt-4">
          <CardTitle className="text-sm font-medium text-fg-muted">
            {t("notifications.stat.total")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-2xl font-semibold text-fg">{counts.total}</p>
        </CardContent>
      </Card>
      <Card data-slot="stat-card">
        <CardHeader className="px-4 pb-2 pt-4">
          <CardTitle className="text-sm font-medium text-fg-muted">
            {t("notifications.stat.sent")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-2xl font-semibold text-fg">{counts.sent}</p>
        </CardContent>
      </Card>
      <Card data-slot="stat-card">
        <CardHeader className="px-4 pb-2 pt-4">
          <CardTitle className="text-sm font-medium text-fg-muted">
            {t("notifications.stat.delivered")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-2xl font-semibold text-fg">{counts.delivered}</p>
        </CardContent>
      </Card>
      <Card data-slot="stat-card">
        <CardHeader className="px-4 pb-2 pt-4">
          <CardTitle className="text-sm font-medium text-fg-muted">
            {t("notifications.stat.failed")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-2xl font-semibold text-fg">{counts.failed}</p>
        </CardContent>
      </Card>
    </div>
  );
}

/** The notifications list: stat cards, a search bar and a table of notifications. */
export function NotificationsList({ view, search, baseHref }: NotificationsListProps) {
  const filtered = view.items;

  return (
    <div data-slot="notifications-list" className="flex flex-col gap-6">
      <PageHeader title={t("notifications.listTitle")} description={t("notifications.listIntro")} />
      <StatCards counts={view.counts} />
      <div className="flex flex-col gap-4">
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="search"
            value={search.value}
            onChange={(e: ChangeEvent<HTMLInputElement>) => search.onChange(e.target.value)}
            placeholder={t("notifications.searchPlaceholder")}
            className="h-10 w-full rounded-md border border-line bg-surface pl-9 pr-3 text-sm text-fg placeholder:text-fg-muted focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        {filtered.length === 0 ? (
          <EmptyState
            title={t("notifications.emptyTitle")}
            description={t("notifications.emptyBody")}
          />
        ) : (
          <Table data-slot="notifications-table">
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("notifications.caption", { count: filtered.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("notifications.column.subject")}</TableHead>
                <TableHead>{t("notifications.column.channel")}</TableHead>
                <TableHead>{t("notifications.column.status")}</TableHead>
                <TableHead>{t("notifications.column.recipient")}</TableHead>
                <TableHead>{t("notifications.column.sentAt")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="align-top">
                    <Link
                      href={hrefFor(NOTIFICATION_SCREEN, { notificationId: item.id }) as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {item.subject}
                    </Link>
                  </TableCell>
                  <TableCell className="align-top">
                    <Badge tone="neutral">{t(`notifications.channel.${item.channel}`)}</Badge>
                  </TableCell>
                  <TableCell className="align-top">
                    <StatusChip status={item.status} />
                  </TableCell>
                  <TableCell className="align-top text-fg-muted">{item.recipient}</TableCell>
                  <TableCell className="align-top whitespace-nowrap text-fg-muted">
                    {item.sentAt}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}

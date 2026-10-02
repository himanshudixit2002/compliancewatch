"use client";

import { useId, useState } from "react";
import Link from "next/link";
import {
  EmptyState,
  Field,
  Input,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { filterNotificationRows } from "./notification-rows";
import type { NotificationRow } from "./notification-rows";

export interface NotificationsTableProps {
  rows: readonly NotificationRow[];
}

/** The notifications table with a search box that narrows it as you type. */
export function NotificationsTable({ rows }: NotificationsTableProps) {
  const searchId = useId();
  const [query, setQuery] = useState("");
  const shown = filterNotificationRows(rows, query);

  return (
    <div className="flex flex-col gap-4">
      <Field
        id={searchId}
        label={t("notificationLog.search")}
        description={t("notificationLog.searchHelp")}
      >
        <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
      </Field>
      {shown.length === 0 ? (
        <EmptyState
          title={t("notificationLog.noMatchTitle")}
          body={t("notificationLog.noMatchBody", { query: query.trim() })}
        />
      ) : (
        <Table data-slot="notifications-table">
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("notificationLog.caption", { shown: shown.length, total: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("notificationLog.column.subject")}</TableHead>
              <TableHead scope="col">{t("notificationLog.column.channel")}</TableHead>
              <TableHead scope="col">{t("notificationLog.column.state")}</TableHead>
              <TableHead scope="col">{t("notificationLog.column.recipient")}</TableHead>
              <TableHead scope="col">{t("notificationLog.column.sentAt")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-notification={row.id}>
                <TableCell className="align-top">
                  <Link href={row.href} className="text-primary underline-offset-2 hover:underline">
                    {row.subject}
                  </Link>
                </TableCell>
                <TableCell className="align-top">{row.channelLabel}</TableCell>
                <TableCell className="align-top">
                  <StatusChip status={row.state} tone={row.tone} label={row.stateLabel} />
                </TableCell>
                <TableCell className="align-top text-fg-muted">{row.recipient}</TableCell>
                <TableCell className="align-top whitespace-nowrap text-fg-muted">
                  {row.sentLabel}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

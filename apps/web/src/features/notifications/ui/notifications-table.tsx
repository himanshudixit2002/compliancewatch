import type { Route } from "next";
import Link from "next/link";
import {
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
import { formatDateTime } from "@/shared/lib/dates";
import type { NotificationRow } from "../model/notifications";

export interface NotificationsTableProps {
  rows: readonly NotificationRow[];
}

/**
 * A page of notifications, newest first: each named by its template (the service keeps no
 * subject) with the occasion, the channel and the masked address, the delivery state, the
 * attempts and when it was queued and last changed. The template opens the notification.
 */
export function NotificationsTable({ rows }: NotificationsTableProps) {
  return (
    <Table data-slot="notifications-table" scrollLabel={t("notificationLog.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("notificationLog.caption", { count: rows.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("notificationLog.column.message")}</TableHead>
          <TableHead>{t("notificationLog.column.to")}</TableHead>
          <TableHead>{t("notificationLog.column.state")}</TableHead>
          <TableHead>{t("notificationLog.column.attempts")}</TableHead>
          <TableHead>{t("notificationLog.column.created")}</TableHead>
          <TableHead>{t("notificationLog.column.updated")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-notification={row.id} data-state={row.state}>
            <TableCell className="align-top">
              <div className="flex flex-col gap-1">
                <Link
                  href={row.href as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {row.title}
                </Link>
                <code className="font-mono text-xs text-fg-muted">{row.templateKey}</code>
                <span className="text-xs text-fg-muted">{row.occasionLabel}</span>
              </div>
            </TableCell>
            <TableCell className="align-top">
              <div className="flex flex-col gap-1">
                <span>{row.channelLabel}</span>
                <span className="font-mono text-xs text-fg-muted">{row.to}</span>
              </div>
            </TableCell>
            <TableCell className="align-top">
              <StatusChip status={row.state} tone={row.tone} label={row.stateLabel} />
            </TableCell>
            <TableCell className="align-top">{row.attempts}</TableCell>
            <TableCell className="align-top whitespace-nowrap text-fg-muted">
              {formatDateTime(row.createdAt)}
            </TableCell>
            <TableCell className="align-top whitespace-nowrap text-fg-muted">
              {formatDateTime(row.updatedAt)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

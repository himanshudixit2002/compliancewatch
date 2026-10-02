"use client";

import { useId, useState } from "react";
import {
  EmptyState,
  Field,
  Select,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { MessageKey } from "@/shared/i18n";
import { t } from "@/shared/i18n";
import { DISPATCH_FILTERS, filterDispatchRows, isDispatchFilter } from "./dispatch-rows";
import type { DispatchFilter, DispatchRow } from "./dispatch-rows";

export interface DispatchLogTableProps {
  rows: readonly DispatchRow[];
}

const FILTER_LABEL: Readonly<Record<DispatchFilter, MessageKey>> = {
  all: "adminNotifications.filter.all",
  pending: "adminNotifications.filter.pending",
  delivered: "adminNotifications.filter.delivered",
  failed: "adminNotifications.filter.failed",
};

/** The latest dispatches, narrowed by delivery outcome. */
export function DispatchLogTable({ rows }: DispatchLogTableProps) {
  const filterId = useId();
  const [filter, setFilter] = useState<DispatchFilter>("all");
  const shown = filterDispatchRows(rows, filter);

  return (
    <div className="flex flex-col gap-4">
      <Field id={filterId} label={t("adminNotifications.filter.label")} className="sm:max-w-xs">
        <Select
          value={filter}
          onChange={(event) => {
            if (isDispatchFilter(event.target.value)) setFilter(event.target.value);
          }}
          options={DISPATCH_FILTERS.map((value) => ({ value, label: t(FILTER_LABEL[value]) }))}
        />
      </Field>
      {shown.length === 0 ? (
        <EmptyState
          title={t("adminNotifications.dispatch.noMatchTitle")}
          body={t("adminNotifications.dispatch.noMatchBody")}
        />
      ) : (
        <Table data-slot="dispatch-table">
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("adminNotifications.dispatch.caption", { shown: shown.length, total: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("adminNotifications.column.occasion")}</TableHead>
              <TableHead scope="col">{t("adminNotifications.column.channel")}</TableHead>
              <TableHead scope="col">{t("adminNotifications.column.recipient")}</TableHead>
              <TableHead scope="col">{t("adminNotifications.column.state")}</TableHead>
              <TableHead scope="col">{t("adminNotifications.column.created")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-dispatch={row.id}>
                <TableCell>{row.occasionLabel}</TableCell>
                <TableCell>{row.channelLabel}</TableCell>
                <TableCell className="text-fg-muted">{row.recipient}</TableCell>
                <TableCell>
                  <StatusChip status={row.state} tone={row.tone} label={row.stateLabel} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-fg-muted">
                  {row.createdLabel}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

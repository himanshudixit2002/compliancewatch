"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  Badge,
  EmptyState,
  Field,
  Input,
  Select,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL, NO_REPORT_FILTERS, filterReportRows, type ReportRow } from "./report-filters";

export interface ReportsTableProps {
  rows: readonly ReportRow[];
  severityOptions: readonly SelectOption[];
  statusOptions: readonly SelectOption[];
}

/**
 * The error reports in a table, narrowed in the browser by a search over the title and what
 * each report is about, and by severity and status. A status line says how many are shown.
 */
export function ReportsTable({ rows, severityOptions, statusOptions }: ReportsTableProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_REPORT_FILTERS);
  const shown = filterReportRows(rows, filters);

  return (
    <div data-slot="reports-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem_12rem]">
        <Field id={`${id}-search`} label={t("adminErrorReports.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-severity`} label={t("adminErrorReports.filter.severity")}>
          <Select
            value={filters.severity}
            onChange={(event) => setFilters({ ...filters, severity: event.target.value })}
            options={[
              { value: ALL, label: t("adminErrorReports.filter.allSeverities") },
              ...severityOptions,
            ]}
          />
        </Field>
        <Field id={`${id}-status`} label={t("adminErrorReports.filter.status")}>
          <Select
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            options={[
              { value: ALL, label: t("adminErrorReports.filter.allStatuses") },
              ...statusOptions,
            ]}
          />
        </Field>
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("adminErrorReports.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState
          title={t("adminErrorReports.noMatch.title")}
          body={t("adminErrorReports.noMatch.body")}
        />
      ) : (
        <Table>
          <TableCaption className="sr-only">{t("adminErrorReports.caption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("adminErrorReports.column.report")}</TableHead>
              <TableHead scope="col">{t("adminErrorReports.column.subject")}</TableHead>
              <TableHead scope="col">{t("adminErrorReports.column.severity")}</TableHead>
              <TableHead scope="col">{t("adminErrorReports.column.status")}</TableHead>
              <TableHead scope="col">{t("adminErrorReports.column.reported")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-report={row.id}>
                <TableCell className="max-w-md whitespace-normal">
                  {row.href === null ? (
                    <span className="font-medium text-fg">{row.title}</span>
                  ) : (
                    <Link
                      href={row.href}
                      className="font-medium text-fg underline-offset-4 hover:underline"
                    >
                      {row.title}
                    </Link>
                  )}
                  <p className="line-clamp-2 text-xs text-fg-muted">{row.message}</p>
                </TableCell>
                <TableCell className="whitespace-normal">{row.subject}</TableCell>
                <TableCell>
                  <Badge tone={row.severityTone}>{row.severityLabel}</Badge>
                </TableCell>
                <TableCell>
                  <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
                </TableCell>
                <TableCell className="text-fg-muted">{row.reportedLabel}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

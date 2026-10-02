"use client";

import { useId, useState } from "react";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Select,
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
import { ALL, NO_REPORT_FILTERS, filterReports, type ReportRow } from "./report-filters";

export interface ReportsTableProps {
  rows: readonly ReportRow[];
  formatOptions: readonly SelectOption[];
  statusOptions: readonly SelectOption[];
}

/**
 * The reports in a table, narrowed in the browser by name, format and status; a ready report
 * links to its file. A status line says how many of the reports are shown.
 */
export function ReportsTable({ rows, formatOptions, statusOptions }: ReportsTableProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_REPORT_FILTERS);
  const shown = filterReports(rows, filters);

  return (
    <div data-slot="reports-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_10rem_10rem]">
        <Field id={`${id}-search`} label={t("reports.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-format`} label={t("reports.filter.format")}>
          <Select
            value={filters.format}
            onChange={(event) => setFilters({ ...filters, format: event.target.value })}
            options={[{ value: ALL, label: t("reports.filter.allFormats") }, ...formatOptions]}
          />
        </Field>
        <Field id={`${id}-status`} label={t("reports.filter.status")}>
          <Select
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            options={[{ value: ALL, label: t("reports.filter.allStatuses") }, ...statusOptions]}
          />
        </Field>
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("reports.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState title={t("reports.noMatch.title")} body={t("reports.noMatch.body")} />
      ) : (
        <Table>
          <TableCaption className="sr-only">{t("reports.caption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("reports.column.name")}</TableHead>
              <TableHead scope="col">{t("reports.column.format")}</TableHead>
              <TableHead scope="col">{t("reports.column.status")}</TableHead>
              <TableHead scope="col">{t("reports.column.generated")}</TableHead>
              <TableHead scope="col">{t("reports.column.size")}</TableHead>
              <TableHead scope="col">{t("reports.column.file")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-report={row.id}>
                <TableCell className="font-medium text-fg">{row.name}</TableCell>
                <TableCell>{row.formatLabel}</TableCell>
                <TableCell>
                  <Badge tone={row.statusTone}>{row.statusLabel}</Badge>
                </TableCell>
                <TableCell>{row.generatedAt}</TableCell>
                <TableCell>{row.size}</TableCell>
                <TableCell>
                  {row.downloadUrl === null ? (
                    <span className="text-fg-muted">{t("reports.notReady")}</span>
                  ) : (
                    <Button asChild variant="secondary" size="sm">
                      <a href={row.downloadUrl} download>
                        {t("reports.download")}
                        <span className="sr-only"> {row.name}</span>
                      </a>
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

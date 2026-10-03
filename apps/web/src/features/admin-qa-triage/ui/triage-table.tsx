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
import { ALL, NO_TRIAGE_FILTERS, filterTriageRows, type TriageRow } from "./triage-filters";

export interface TriageTableProps {
  rows: readonly TriageRow[];
  statusOptions: readonly SelectOption[];
  reasonOptions: readonly SelectOption[];
}

/**
 * The triage queue in a table, narrowed in the browser by a search over the question and its
 * topic and by status and reason. A status line says how many of the questions are shown.
 */
export function TriageTable({ rows, statusOptions, reasonOptions }: TriageTableProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_TRIAGE_FILTERS);
  const shown = filterTriageRows(rows, filters);

  return (
    <div data-slot="triage-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem_12rem]">
        <Field id={`${id}-search`} label={t("adminQaTriage.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-status`} label={t("adminQaTriage.filter.status")}>
          <Select
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            options={[
              { value: ALL, label: t("adminQaTriage.filter.allStatuses") },
              ...statusOptions,
            ]}
          />
        </Field>
        <Field id={`${id}-reason`} label={t("adminQaTriage.filter.reason")}>
          <Select
            value={filters.reason}
            onChange={(event) => setFilters({ ...filters, reason: event.target.value })}
            options={[
              { value: ALL, label: t("adminQaTriage.filter.allReasons") },
              ...reasonOptions,
            ]}
          />
        </Field>
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("adminQaTriage.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState
          title={t("adminQaTriage.noMatch.title")}
          body={t("adminQaTriage.noMatch.body")}
        />
      ) : (
        <Table>
          <TableCaption className="sr-only">{t("adminQaTriage.caption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("adminQaTriage.column.question")}</TableHead>
              <TableHead scope="col">{t("adminQaTriage.column.reason")}</TableHead>
              <TableHead scope="col">{t("adminQaTriage.column.priority")}</TableHead>
              <TableHead scope="col">{t("adminQaTriage.column.status")}</TableHead>
              <TableHead scope="col">{t("adminQaTriage.column.assignee")}</TableHead>
              <TableHead scope="col">{t("adminQaTriage.column.added")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-triage={row.id}>
                <TableCell className="whitespace-normal">
                  {row.href === null ? (
                    <span className="font-medium text-fg">{row.question}</span>
                  ) : (
                    <Link
                      href={row.href}
                      className="font-medium text-fg underline-offset-4 hover:underline"
                    >
                      {row.question}
                    </Link>
                  )}
                  <p className="text-xs text-fg-muted">{row.category}</p>
                </TableCell>
                <TableCell>{row.reasonLabel}</TableCell>
                <TableCell>
                  <Badge tone={row.priorityTone}>{row.priorityLabel}</Badge>
                </TableCell>
                <TableCell>
                  <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
                </TableCell>
                <TableCell>{row.assignee}</TableCell>
                <TableCell className="text-fg-muted">{row.createdLabel}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

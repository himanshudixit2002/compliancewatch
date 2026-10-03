"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
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
  cn,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import {
  ALL,
  NO_OBLIGATION_FILTERS,
  OVERDUE,
  filterObligations,
  type ObligationRow,
} from "./obligation-rows";

export interface ObligationsTableProps {
  rows: readonly ObligationRow[];
  /** One option per status, in order; "All statuses" and "Overdue" come first. */
  statusOptions: readonly SelectOption[];
}

function Rows({ rows }: { rows: readonly ObligationRow[] }) {
  return (
    <Table>
      <TableCaption className="sr-only">{t("obligations.caption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("obligations.column.obligation")}</TableHead>
          <TableHead scope="col">{t("obligations.column.status")}</TableHead>
          <TableHead scope="col">{t("obligations.column.due")}</TableHead>
          <TableHead scope="col">{t("obligations.column.evidence")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-obligation={row.id}>
            <TableCell className="whitespace-normal">
              <Link
                href={row.href}
                className="font-medium text-fg underline-offset-4 hover:underline"
              >
                {row.title}
              </Link>
              {row.period === null ? null : <p className="text-xs text-fg-muted">{row.period}</p>}
            </TableCell>
            <TableCell>
              <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
            </TableCell>
            <TableCell>
              <span className="block">{row.due}</span>
              {row.dueNote === null ? null : (
                <span
                  data-slot="due-note"
                  className={cn(
                    "block text-xs",
                    row.overdue ? "font-medium text-danger" : "text-fg-muted",
                  )}
                >
                  {row.dueNote}
                </span>
              )}
            </TableCell>
            <TableCell className="text-fg-muted">{row.evidence}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The obligations in a table, narrowed in the browser by status (or to the overdue ones) and by
 * a search over the title and the period. Each title opens the obligation's own page.
 */
export function ObligationsTable({ rows, statusOptions }: ObligationsTableProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_OBLIGATION_FILTERS);
  const shown = filterObligations(rows, filters);

  return (
    <div data-slot="obligations-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
        <Field id={`${id}-search`} label={t("obligations.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-status`} label={t("obligations.filter.status")}>
          <Select
            value={filters.status}
            onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            options={[
              { value: ALL, label: t("obligations.filter.all") },
              { value: OVERDUE, label: t("obligations.filter.overdue") },
              ...statusOptions,
            ]}
          />
        </Field>
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("obligations.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState title={t("obligations.noMatch.title")} body={t("obligations.noMatch.body")} />
      ) : (
        <Rows rows={shown} />
      )}
    </div>
  );
}

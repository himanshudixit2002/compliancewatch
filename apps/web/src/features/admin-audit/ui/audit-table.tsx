"use client";

import { useId, useState } from "react";
import {
  Badge,
  Button,
  DateField,
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
import {
  ALL,
  NO_AUDIT_FILTERS,
  filterAuditRows,
  type AuditFilters,
  type AuditRow,
} from "./audit-filters";

export interface AuditTableProps {
  /** The events, newest first. */
  rows: readonly AuditRow[];
  categoryOptions: readonly SelectOption[];
}

function EventRow({ row }: { row: AuditRow }) {
  return (
    <TableRow data-event={row.id}>
      <TableCell className="align-top text-fg-muted">{row.at}</TableCell>
      <TableCell className="align-top font-medium text-fg">{row.actor}</TableCell>
      <TableCell className="align-top">
        <div className="flex flex-col items-start gap-1">
          <code className="font-mono text-xs text-fg">{row.action}</code>
          <Badge tone="neutral">{row.categoryLabel}</Badge>
        </div>
      </TableCell>
      <TableCell className="align-top">
        <span className="block">{row.subjectType}</span>
        <code className="block font-mono text-xs text-fg-muted">{row.subjectId}</code>
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        {row.changes.length === 0 ? (
          <span className="text-fg-muted">{t("adminAudit.noChanges")}</span>
        ) : (
          <ul className="flex flex-col gap-1">
            {row.changes.map((change, index) => (
              <li key={index}>{change}</li>
            ))}
          </ul>
        )}
      </TableCell>
    </TableRow>
  );
}

/**
 * The audit events in a table, narrowed in the browser by a search over the actor, the action
 * and the record, by category and by a range of IST dates.
 */
export function AuditTable({ rows, categoryOptions }: AuditTableProps) {
  const id = useId();
  const [filters, setFilters] = useState<AuditFilters>(NO_AUDIT_FILTERS);
  const shown = filterAuditRows(rows, filters);
  const change = (patch: Partial<AuditFilters>) =>
    setFilters((current) => ({ ...current, ...patch }));

  return (
    <div data-slot="audit-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_12rem_auto_auto]">
        <Field id={`${id}-search`} label={t("adminAudit.filter.search")}>
          <Input
            type="search"
            value={filters.search}
            onChange={(event) => change({ search: event.target.value })}
          />
        </Field>
        <Field id={`${id}-category`} label={t("adminAudit.filter.category")}>
          <Select
            value={filters.category}
            onChange={(event) => change({ category: event.target.value })}
            options={[
              { value: ALL, label: t("adminAudit.filter.allCategories") },
              ...categoryOptions,
            ]}
          />
        </Field>
        <DateField
          id={`${id}-from`}
          label={t("adminAudit.filter.from")}
          value={filters.from}
          max={filters.to === "" ? undefined : filters.to}
          onChange={(event) => change({ from: event.target.value })}
        />
        <DateField
          id={`${id}-to`}
          label={t("adminAudit.filter.to")}
          value={filters.to}
          min={filters.from === "" ? undefined : filters.from}
          onChange={(event) => change({ to: event.target.value })}
        />
      </div>
      <p role="status" className="text-sm text-fg-muted">
        {t("adminAudit.shown", { shown: shown.length, total: rows.length })}
      </p>
      {shown.length === 0 ? (
        <EmptyState
          title={t("adminAudit.noMatch.title")}
          body={t("adminAudit.noMatch.body")}
          action={
            <Button variant="secondary" onClick={() => setFilters(NO_AUDIT_FILTERS)}>
              {t("adminAudit.clearFilters")}
            </Button>
          }
        />
      ) : (
        <Table>
          <TableCaption className="sr-only">{t("adminAudit.caption")}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("adminAudit.column.when")}</TableHead>
              <TableHead>{t("adminAudit.column.actor")}</TableHead>
              <TableHead>{t("adminAudit.column.action")}</TableHead>
              <TableHead>{t("adminAudit.column.subject")}</TableHead>
              <TableHead>{t("adminAudit.column.changes")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <EventRow key={row.id} row={row} />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import {
  EmptyState,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL, filterEvidenceRows, type EvidenceRow } from "./evidence-rows";

export interface EvidenceTableProps {
  rows: readonly EvidenceRow[];
  /** One tab per review status, in order; an "All files" tab comes first. */
  statusTabs: readonly SelectOption[];
}

function FilesTable({ rows }: { rows: readonly EvidenceRow[] }) {
  if (rows.length === 0) {
    return <EmptyState title={t("evidence.noMatch.title")} body={t("evidence.noMatch.body")} />;
  }
  return (
    <Table>
      <TableCaption className="sr-only">{t("evidence.tableCaption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("evidence.column.file")}</TableHead>
          <TableHead scope="col">{t("evidence.column.size")}</TableHead>
          <TableHead scope="col">{t("evidence.column.uploadedBy")}</TableHead>
          <TableHead scope="col">{t("evidence.column.uploadedAt")}</TableHead>
          <TableHead scope="col">{t("evidence.column.status")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-item={row.id}>
            <TableCell className="font-medium text-fg">{row.fileName}</TableCell>
            <TableCell className="text-fg-muted">{row.size}</TableCell>
            <TableCell>{row.uploadedBy}</TableCell>
            <TableCell className="text-fg-muted">
              <time dateTime={row.uploadedAt}>{row.uploadedLabel}</time>
            </TableCell>
            <TableCell>
              <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The evidence files under review-status tabs, narrowed in the browser; a status line says how
 * many of the files are shown.
 */
export function EvidenceTable({ rows, statusTabs }: EvidenceTableProps) {
  const [status, setStatus] = useState(ALL);
  const shown = filterEvidenceRows(rows, status);
  const tabs = [{ value: ALL, label: t("evidence.tab.all") }, ...statusTabs];

  return (
    <div data-slot="evidence-table" className="flex flex-col gap-4">
      <Tabs value={status} onValueChange={setStatus}>
        <TabsList aria-label={t("evidence.tabs")}>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <p role="status" className="text-sm text-fg-muted">
          {t("evidence.shown", { shown: shown.length, total: rows.length })}
        </p>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <FilesTable rows={shown} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

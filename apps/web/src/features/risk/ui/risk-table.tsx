"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  Badge,
  EmptyState,
  Field,
  Input,
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
import { ALL, filterRisks, type RiskRow } from "./risk-filters";

export interface RiskTableProps {
  rows: readonly RiskRow[];
  /** One tab per status, in order; an "All risks" tab comes first. */
  statusTabs: readonly SelectOption[];
}

function RisksTable({ rows }: { rows: readonly RiskRow[] }) {
  if (rows.length === 0) {
    return <EmptyState title={t("risk.noMatch.title")} body={t("risk.noMatch.body")} />;
  }
  return (
    <Table>
      <TableCaption className="sr-only">{t("risk.caption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("risk.column.risk")}</TableHead>
          <TableHead scope="col">{t("risk.column.severity")}</TableHead>
          <TableHead scope="col">{t("risk.column.status")}</TableHead>
          <TableHead scope="col">{t("risk.column.likelihood")}</TableHead>
          <TableHead scope="col">{t("risk.column.identified")}</TableHead>
          <TableHead scope="col">{t("risk.column.owner")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-risk={row.id}>
            <TableCell className="whitespace-normal">
              <Link
                href={row.href}
                className="font-medium text-fg underline-offset-4 hover:underline"
              >
                {row.title}
              </Link>
              <p className="text-xs text-fg-muted">{row.description}</p>
            </TableCell>
            <TableCell>
              <Badge tone={row.severityTone}>{row.severityLabel}</Badge>
            </TableCell>
            <TableCell>
              <Badge tone={row.statusTone}>{row.statusLabel}</Badge>
            </TableCell>
            <TableCell>{row.likelihood}</TableCell>
            <TableCell>{row.identifiedAt}</TableCell>
            <TableCell>{row.owner}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The register in a table under status tabs, narrowed in the browser by a search over the
 * title and the owner. Each title opens the risk's own page.
 */
export function RiskTable({ rows, statusTabs }: RiskTableProps) {
  const id = useId();
  const [status, setStatus] = useState(ALL);
  const [search, setSearch] = useState("");
  const shown = filterRisks(rows, { status, search });
  const tabs = [{ value: ALL, label: t("risk.tab.all") }, ...statusTabs];

  return (
    <div data-slot="risk-table" className="flex flex-col gap-4">
      <Field id={`${id}-search`} label={t("risk.filter.search")} className="sm:max-w-sm">
        <Input type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
      </Field>
      <Tabs value={status} onValueChange={setStatus}>
        <TabsList aria-label={t("risk.tabs")}>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <p role="status" className="text-sm text-fg-muted">
          {t("risk.shown", { shown: shown.length, total: rows.length })}
        </p>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <RisksTable rows={shown} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

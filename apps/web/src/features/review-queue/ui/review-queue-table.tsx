"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  Badge,
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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL, filterReviewItems, type ReviewRow } from "./review-filters";

export interface ReviewQueueTableProps {
  rows: readonly ReviewRow[];
  /** One tab per status, in order; an "All" tab follows them. */
  statusTabs: readonly SelectOption[];
  typeOptions: readonly SelectOption[];
  /** The tab shown first, normally the pending items. */
  initialStatus: string;
}

function ReviewTable({ rows }: { rows: readonly ReviewRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState title={t("reviewQueue.noMatch.title")} body={t("reviewQueue.noMatch.body")} />
    );
  }
  return (
    <Table>
      <TableCaption className="sr-only">{t("reviewQueue.caption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("reviewQueue.column.item")}</TableHead>
          <TableHead scope="col">{t("reviewQueue.column.type")}</TableHead>
          <TableHead scope="col">{t("reviewQueue.column.priority")}</TableHead>
          <TableHead scope="col">{t("reviewQueue.column.business")}</TableHead>
          <TableHead scope="col">{t("reviewQueue.column.submitted")}</TableHead>
          <TableHead scope="col">{t("reviewQueue.column.status")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-review={row.id}>
            <TableCell className="whitespace-normal">
              <Link
                href={row.href}
                className="font-medium text-fg underline-offset-4 hover:underline"
              >
                {row.title}
              </Link>
              <p className="text-xs text-fg-muted">{row.description}</p>
            </TableCell>
            <TableCell>{row.typeLabel}</TableCell>
            <TableCell>
              <Badge tone={row.priorityTone}>{row.priorityLabel}</Badge>
            </TableCell>
            <TableCell>{row.businessName}</TableCell>
            <TableCell>
              <span className="block">{row.submittedBy}</span>
              <span className="block text-xs text-fg-muted">{row.submittedAt}</span>
            </TableCell>
            <TableCell>
              <Badge tone={row.statusTone}>{row.statusLabel}</Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The queue in a table under status tabs, narrowed in the browser by item type and by a search
 * over the title and the business. Each title opens the item's own page for the decision.
 */
export function ReviewQueueTable({
  rows,
  statusTabs,
  typeOptions,
  initialStatus,
}: ReviewQueueTableProps) {
  const id = useId();
  const [status, setStatus] = useState(initialStatus);
  const [type, setType] = useState(ALL);
  const [search, setSearch] = useState("");
  const shown = filterReviewItems(rows, { status, type, search });
  const tabs = [...statusTabs, { value: ALL, label: t("reviewQueue.tab.all") }];

  return (
    <div data-slot="review-queue-table" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
        <Field id={`${id}-search`} label={t("reviewQueue.filter.search")}>
          <Input type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
        </Field>
        <Field id={`${id}-type`} label={t("reviewQueue.filter.type")}>
          <Select
            value={type}
            onChange={(event) => setType(event.target.value)}
            options={[{ value: ALL, label: t("reviewQueue.filter.allTypes") }, ...typeOptions]}
          />
        </Field>
      </div>
      <Tabs value={status} onValueChange={setStatus}>
        <TabsList aria-label={t("reviewQueue.tabs")}>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <p role="status" className="text-sm text-fg-muted">
          {t("reviewQueue.shown", { shown: shown.length, total: rows.length })}
        </p>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <ReviewTable rows={shown} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

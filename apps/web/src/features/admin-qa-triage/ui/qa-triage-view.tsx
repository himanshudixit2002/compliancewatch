import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  sortTriageItems,
  triageCounts,
  triagePriorityLabel,
  triagePriorityTone,
  triageReasonLabel,
  triageReasonOptions,
  triageStatusLabel,
  triageStatusOptions,
  triageStatusTone,
  type TriageItem,
} from "../model/qa-triage";
import type { TriageRow } from "./triage-filters";
import { TriageTable } from "./triage-table";

export interface AdminQaTriageViewProps {
  items: readonly TriageItem[];
  /** Where an analyst reviews one item; without it the questions are not links. */
  hrefFor?: (itemId: string) => Route;
}

function triageRow(item: TriageItem, hrefFor?: (itemId: string) => Route): TriageRow {
  return {
    id: item.id,
    question: item.question,
    category: item.category,
    href: hrefFor === undefined ? null : hrefFor(item.id),
    reason: item.reason,
    reasonLabel: triageReasonLabel(item.reason),
    priorityLabel: triagePriorityLabel(item.priority),
    priorityTone: triagePriorityTone(item.priority),
    status: item.status,
    statusLabel: triageStatusLabel(item.status),
    statusTone: triageStatusTone(item.status),
    assignee: item.assignee ?? t("adminQaTriage.unassigned"),
    createdLabel: formatDateTime(item.createdAt),
  };
}

/**
 * The Q&A triage queue: how many questions there are, open and closed, then the queue with its
 * filters, open questions first and the most urgent at the top, or an empty state when nothing
 * waits for triage.
 */
export function AdminQaTriageView({ items, hrefFor }: AdminQaTriageViewProps) {
  const counts = triageCounts(items);
  return (
    <div data-slot="admin-qa-triage" className="flex flex-col gap-6">
      <PageHeader title={t("adminQaTriage.title")} description={t("adminQaTriage.intro")} />
      {items.length === 0 ? (
        <EmptyState title={t("adminQaTriage.empty.title")} body={t("adminQaTriage.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label={t("adminQaTriage.stat.total")} value={counts.total} tone="info" />
            <StatCard
              label={t("adminQaTriage.stat.open")}
              value={counts.open}
              tone={counts.open > 0 ? "warning" : "neutral"}
            />
            <StatCard label={t("adminQaTriage.stat.closed")} value={counts.closed} tone="success" />
          </div>
          <TriageTable
            rows={sortTriageItems(items).map((item) => triageRow(item, hrefFor))}
            statusOptions={triageStatusOptions()}
            reasonOptions={triageReasonOptions()}
          />
        </>
      )}
    </div>
  );
}

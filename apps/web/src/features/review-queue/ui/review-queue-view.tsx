import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  reviewCounts,
  reviewPriorityLabel,
  reviewPriorityTone,
  reviewStatusLabel,
  reviewStatusTabs,
  reviewStatusTone,
  reviewTypeLabel,
  reviewTypeOptions,
  type ReviewItem,
} from "../model/review-queue";
import type { ReviewRow } from "./review-filters";
import { ReviewQueueTable } from "./review-queue-table";

export interface ReviewQueueViewProps {
  items: readonly ReviewItem[];
  /** The page where a reviewer reads one item and decides on it. */
  hrefFor: (itemId: string) => Route;
}

function reviewRow(item: ReviewItem, hrefFor: (itemId: string) => Route): ReviewRow {
  return {
    id: item.id,
    title: item.title,
    description: item.description,
    href: hrefFor(item.id),
    type: item.type,
    typeLabel: reviewTypeLabel(item.type),
    status: item.status,
    statusLabel: reviewStatusLabel(item.status),
    statusTone: reviewStatusTone(item.status),
    priorityLabel: reviewPriorityLabel(item.priority),
    priorityTone: reviewPriorityTone(item.priority),
    businessName: item.businessName,
    submittedBy: item.submittedBy,
    submittedAt: formatDateTime(item.submittedAt),
  };
}

/**
 * The review queue for the operations team: how many items there are in each state, then the
 * queue under status tabs (pending first), or an empty state when nothing was ever submitted.
 */
export function ReviewQueueView({ items, hrefFor }: ReviewQueueViewProps) {
  const counts = reviewCounts(items);
  return (
    <div data-slot="review-queue" className="flex flex-col gap-6">
      <PageHeader title={t("reviewQueue.title")} description={t("reviewQueue.description")} />
      {items.length === 0 ? (
        <EmptyState title={t("reviewQueue.empty.title")} body={t("reviewQueue.empty.body")} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("reviewQueue.stat.total")} value={counts.total} tone="info" />
            <StatCard label={t("reviewQueue.stat.pending")} value={counts.pending} tone="warning" />
            <StatCard
              label={t("reviewQueue.stat.approved")}
              value={counts.approved}
              tone="success"
            />
            <StatCard
              label={t("reviewQueue.stat.rejected")}
              value={counts.rejected}
              tone="danger"
            />
          </div>
          <ReviewQueueTable
            rows={items.map((item) => reviewRow(item, hrefFor))}
            statusTabs={reviewStatusTabs()}
            typeOptions={reviewTypeOptions()}
            initialStatus="pending"
          />
        </>
      )}
    </div>
  );
}

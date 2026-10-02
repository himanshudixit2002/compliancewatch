import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import {
  applicabilityLabel,
  applicabilityOptions,
  applicabilityTone,
  changeCounts,
  changeFacts,
  reviewStatusLabel,
  reviewStatusOptions,
  reviewStatusTone,
  shortSummary,
  type ChangeItem,
} from "../model/changes";
import type { ChangeRow } from "./change-filters";
import { ChangesList } from "./changes-list";

export interface ChangesViewProps {
  changes: readonly ChangeItem[];
  /** The detail page of one change. */
  hrefFor: (changeId: string) => Route;
}

function changeRow(change: ChangeItem, hrefFor: (changeId: string) => Route): ChangeRow {
  return {
    id: change.id,
    title: change.title,
    regulator: change.regulator,
    summary: shortSummary(change.summary),
    href: hrefFor(change.id),
    applicability: change.applicability,
    applicabilityLabel: applicabilityLabel(change.applicability),
    applicabilityTone: applicabilityTone(change.applicability),
    reviewStatus: change.reviewStatus,
    reviewLabel: reviewStatusLabel(change.reviewStatus),
    reviewTone: reviewStatusTone(change.reviewStatus),
    facts: changeFacts(change),
    categories: change.categories,
  };
}

/**
 * The regulatory changes for a business: how many there are, how many apply and how many are
 * still in review, then the filterable list, or an empty state before any change is detected.
 */
export function ChangesView({ changes, hrefFor }: ChangesViewProps) {
  const counts = changeCounts(changes);
  return (
    <div data-slot="changes" className="flex flex-col gap-6">
      <PageHeader
        title={t("changes.title")}
        description={t("changes.description", {
          total: counts.total,
          applicable: counts.applicable,
          inReview: counts.inReview,
        })}
      />
      {changes.length === 0 ? (
        <EmptyState title={t("changes.empty.title")} body={t("changes.empty.body")} />
      ) : (
        <ChangesList
          rows={changes.map((change) => changeRow(change, hrefFor))}
          applicabilityOptions={applicabilityOptions()}
          reviewOptions={reviewStatusOptions()}
        />
      )}
    </div>
  );
}

import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The tab or select value that keeps every row. */
export const ALL = "all";

/** One queue item, already worded for the table; the server view derives it from the model. */
export interface ReviewRow {
  id: string;
  title: string;
  description: string;
  href: Route;
  type: string;
  typeLabel: string;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  priorityLabel: string;
  priorityTone: Tone;
  businessName: string;
  submittedBy: string;
  submittedAt: string;
}

export interface ReviewFilters {
  /** A status (the active tab), or ALL. */
  status: string;
  /** An item type, or ALL. */
  type: string;
  /** Matched, ignoring case, against the title and the business's name. */
  search: string;
}

/** The rows that pass every filter, in their original order. */
export function filterReviewItems(
  rows: readonly ReviewRow[],
  filters: ReviewFilters,
): readonly ReviewRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (filters.status === ALL || row.status === filters.status) &&
      (filters.type === ALL || row.type === filters.type) &&
      (term === "" ||
        row.title.toLowerCase().includes(term) ||
        row.businessName.toLowerCase().includes(term)),
  );
}

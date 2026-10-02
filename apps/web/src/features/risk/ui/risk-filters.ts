import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The tab value that keeps every row. */
export const ALL = "all";

/** One risk, already worded for the table; the server view derives it from the model. */
export interface RiskRow {
  id: string;
  title: string;
  description: string;
  href: Route;
  severityLabel: string;
  severityTone: Tone;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  likelihood: string;
  identifiedAt: string;
  owner: string;
}

export interface RiskFilters {
  /** A status (the active tab), or ALL. */
  status: string;
  /** Matched, ignoring case, against the title and the owner. */
  search: string;
}

/** The rows that pass every filter, in their original order. */
export function filterRisks(rows: readonly RiskRow[], filters: RiskFilters): readonly RiskRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (filters.status === ALL || row.status === filters.status) &&
      (term === "" ||
        row.title.toLowerCase().includes(term) ||
        row.owner.toLowerCase().includes(term)),
  );
}

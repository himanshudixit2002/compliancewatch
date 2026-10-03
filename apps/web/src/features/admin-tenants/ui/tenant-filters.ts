import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The tab that keeps every tenant kind. */
export const ALL = "all";

/** One tenant, already worded for the table; the server view derives it from the model. */
export interface TenantRow {
  id: string;
  name: string;
  /** The tenant's own page, or null when the names are not links. */
  href: Route | null;
  kind: string;
  kindLabel: string;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  region: string;
  /** The sign-up date, already formatted. */
  created: string;
  /** Where an admin starts impersonating the tenant, or null when that is not offered. */
  impersonateHref: Route | null;
}

export interface TenantFilters {
  /** A tenant kind (the active tab), or ALL. */
  kind: string;
  /** Matched, ignoring case and surrounding spaces, against the name and the id. */
  search: string;
}

export const NO_TENANT_FILTERS: TenantFilters = { kind: ALL, search: "" };

/** The rows that pass every filter, in their original order. */
export function filterTenants(
  rows: readonly TenantRow[],
  filters: TenantFilters,
): readonly TenantRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (filters.kind === ALL || row.kind === filters.kind) &&
      (term === "" || row.name.toLowerCase().includes(term) || row.id.toLowerCase().includes(term)),
  );
}

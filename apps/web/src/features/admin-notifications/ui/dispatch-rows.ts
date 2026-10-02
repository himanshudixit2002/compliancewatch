import type { Tone } from "@compliancewatch/ui";

/** The dispatch log filter: everything, or one delivery bucket. */
export type DispatchFilter = "all" | "pending" | "delivered" | "failed";

export const DISPATCH_FILTERS: readonly DispatchFilter[] = [
  "all",
  "pending",
  "delivered",
  "failed",
];

/** A dispatch log row with its labels resolved on the server, for the client table. */
export interface DispatchRow {
  id: string;
  occasionLabel: string;
  channelLabel: string;
  recipient: string;
  state: string;
  stateLabel: string;
  tone: Tone;
  bucket: Exclude<DispatchFilter, "all">;
  createdLabel: string;
}

export function isDispatchFilter(value: string): value is DispatchFilter {
  return (DISPATCH_FILTERS as readonly string[]).includes(value);
}

/** The rows in the chosen bucket; "all" keeps every row. */
export function filterDispatchRows(
  rows: readonly DispatchRow[],
  filter: DispatchFilter,
): readonly DispatchRow[] {
  return filter === "all" ? rows : rows.filter((row) => row.bucket === filter);
}

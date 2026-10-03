import type { Tone } from "@compliancewatch/ui";

/** The tab value that keeps every file. */
export const ALL = "all";

/** One file, already worded for the table; the server view derives it from the model. */
export interface EvidenceRow {
  id: string;
  fileName: string;
  size: string;
  uploadedBy: string;
  /** The upload instant, for the time element. */
  uploadedAt: string;
  uploadedLabel: string;
  status: string;
  statusLabel: string;
  statusTone: Tone;
}

/** The files with the chosen review status (the active tab), or every file for ALL, in order. */
export function filterEvidenceRows(
  rows: readonly EvidenceRow[],
  status: string,
): readonly EvidenceRow[] {
  return status === ALL ? rows : rows.filter((row) => row.status === status);
}

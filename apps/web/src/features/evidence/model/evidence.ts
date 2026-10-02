import type { Tone } from "@compliancewatch/ui";

export const EVIDENCE_STATUSES = ["submitted", "accepted", "rejected"] as const;

export type EvidenceStatus = (typeof EVIDENCE_STATUSES)[number];

/** One file attached to an obligation as proof it was met. */
export interface EvidenceItem {
  id: string;
  fileName: string;
  sizeBytes: number;
  uploadedBy: string;
  /** The instant it was uploaded (ISO 8601). */
  uploadedAt: string;
  status: EvidenceStatus;
}

/** An obligation's evidence: what it is for and the files attached so far. */
export interface EvidenceList {
  obligationName: string;
  /** The due date as a date key; null when the obligation has none. */
  dueDate: string | null;
  items: readonly EvidenceItem[];
}

const UNITS = ["B", "KB", "MB", "GB"] as const;

/** "512 B", "1.5 KB", "2 MB": binary multiples, at most one decimal, capped at GB. */
export function formatFileSize(bytes: number): string {
  let value = Math.max(bytes, 0);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${Number(value.toFixed(1))} ${UNITS[unit]}`;
}

const STATUS_TONE: Readonly<Record<EvidenceStatus, Tone>> = {
  submitted: "info",
  accepted: "success",
  rejected: "danger",
};

export function evidenceTone(status: EvidenceStatus): Tone {
  return STATUS_TONE[status];
}

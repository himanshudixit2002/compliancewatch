import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/** Where an uploaded file stands in review: waiting, accepted as proof, or turned down. */
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

/** The figures in the summary row. */
export interface EvidenceCounts {
  total: number;
  submitted: number;
  accepted: number;
  rejected: number;
}

/** The upload form's field names, shared with the server action that reads the file. */
export const EVIDENCE_UPLOAD_FIELDS = { file: "file" } as const;

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

const STATUS_LABEL: Readonly<Record<EvidenceStatus, MessageKey>> = {
  submitted: "evidence.status.submitted",
  accepted: "evidence.status.accepted",
  rejected: "evidence.status.rejected",
};

export function evidenceTone(status: EvidenceStatus): Tone {
  return STATUS_TONE[status];
}

export function evidenceStatusLabel(status: EvidenceStatus): string {
  return t(STATUS_LABEL[status]);
}

/** One tab per review status, in review order. */
export function evidenceStatusTabs(): SelectOption[] {
  return EVIDENCE_STATUSES.map((value) => ({ value, label: evidenceStatusLabel(value) }));
}

export function evidenceCounts(items: readonly EvidenceItem[]): EvidenceCounts {
  const count = (status: EvidenceStatus) => items.filter((item) => item.status === status).length;
  return {
    total: items.length,
    submitted: count("submitted"),
    accepted: count("accepted"),
    rejected: count("rejected"),
  };
}

import type { EvidenceItem } from "@/entities/evidence/types";
import { t } from "@/shared/i18n";

export interface EvidenceView {
  obligationId: string;
  obligationName: string;
  dueDate: string;
  items: EvidenceItem[];
  canUpload: boolean;
  allowedTypes: readonly string[];
}

export function emptyEvidence(obligationId: string, obligationName: string): EvidenceView {
  return {
    obligationId,
    obligationName,
    dueDate: "",
    items: [],
    canUpload: false,
    allowedTypes: ["pdf", "jpg", "png", "docx", "xlsx"],
  };
}

export function evidenceStatusLabel(status: string): string {
  return t(`evidence.status.${status}`);
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

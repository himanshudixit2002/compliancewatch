import type { ReportFormat } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";

export interface ReportView {
  reports: ReportItem[];
  businessId: string;
  totalCount: number;
}

export interface ReportItem {
  id: string;
  name: string;
  kind: string;
  format: ReportFormat;
  status: string;
  generatedAt: string;
  size: string;
  url: string | null;
}

export function emptyReports(businessId: string): ReportView {
  return { reports: [], businessId, totalCount: 0 };
}

export function reportFormatLabel(format: ReportFormat): string {
  return t(`report.format.${format}`);
}

export function reportStatusLabel(status: string): string {
  return t(`report.status.${status}`);
}

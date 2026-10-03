import { t } from "@/shared/i18n";

export interface ErrorReport {
  id: string;
  title: string;
  severity: "low" | "medium" | "high" | "critical";
  status: string;
  source: string;
  message: string;
  stackTrace?: string;
  createdAt: string;
  resolvedAt: string | null;
}

export interface AdminErrorReportsView {
  reports: ErrorReport[];
  totalCount: number;
}

export function emptyAdminErrorReports(): AdminErrorReportsView {
  return { reports: [], totalCount: 0 };
}

export function errorSeverityTone(
  severity: ErrorReport["severity"],
): "success" | "info" | "warning" | "danger" {
  switch (severity) {
    case "low":
      return "info";
    case "medium":
      return "warning";
    case "high":
      return "danger";
    case "critical":
      return "danger";
  }
}

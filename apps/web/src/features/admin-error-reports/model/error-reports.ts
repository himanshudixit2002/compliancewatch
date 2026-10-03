import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The error reports screen: errors people reported in an obligation or a rule, waiting for an
 * analyst's decision. `GET /v1/rulebook/error-reports` has no committed spec yet, so these are
 * plain types; instants are ISO strings and the views format them in IST.
 */

export type ErrorSeverity = "critical" | "high" | "medium" | "low";

/** Open until an analyst decides; resolved when the content was corrected, dismissed when not. */
export type ErrorReportStatus = "open" | "resolved" | "dismissed";

/** Most serious first. */
export const ERROR_SEVERITIES: readonly ErrorSeverity[] = ["critical", "high", "medium", "low"];

export const ERROR_REPORT_STATUSES: readonly ErrorReportStatus[] = [
  "open",
  "resolved",
  "dismissed",
];

/** One reported error. */
export interface ErrorReport {
  id: string;
  /** What is wrong, in one line. */
  title: string;
  /** The reporter's account of the error. */
  message: string;
  /** What the report is about, such as the obligation's name. */
  subject: string;
  severity: ErrorSeverity;
  status: ErrorReportStatus;
  /** When it was reported. */
  reportedAt: string;
}

/** The figures in the summary row. */
export interface ErrorReportCounts {
  total: number;
  open: number;
  /** Open reports that are critical or high. */
  urgent: number;
  resolved: number;
}

const SEVERITY_LABEL: Readonly<Record<ErrorSeverity, MessageKey>> = {
  critical: "adminErrorReports.severity.critical",
  high: "adminErrorReports.severity.high",
  medium: "adminErrorReports.severity.medium",
  low: "adminErrorReports.severity.low",
};

const SEVERITY_TONE: Readonly<Record<ErrorSeverity, Tone>> = {
  critical: "danger",
  high: "danger",
  medium: "warning",
  low: "info",
};

const STATUS_LABEL: Readonly<Record<ErrorReportStatus, MessageKey>> = {
  open: "adminErrorReports.status.open",
  resolved: "adminErrorReports.status.resolved",
  dismissed: "adminErrorReports.status.dismissed",
};

const STATUS_TONE: Readonly<Record<ErrorReportStatus, Tone>> = {
  open: "warning",
  resolved: "success",
  dismissed: "neutral",
};

export function severityLabel(severity: ErrorSeverity): string {
  return t(SEVERITY_LABEL[severity]);
}

export function severityTone(severity: ErrorSeverity): Tone {
  return SEVERITY_TONE[severity];
}

export function reportStatusLabel(status: ErrorReportStatus): string {
  return t(STATUS_LABEL[status]);
}

export function reportStatusTone(status: ErrorReportStatus): Tone {
  return STATUS_TONE[status];
}

export function severityOptions(): SelectOption[] {
  return ERROR_SEVERITIES.map((value) => ({ value, label: severityLabel(value) }));
}

export function reportStatusOptions(): SelectOption[] {
  return ERROR_REPORT_STATUSES.map((value) => ({ value, label: reportStatusLabel(value) }));
}

/** True for a report still open and critical or high. */
export function isUrgent(report: Pick<ErrorReport, "severity" | "status">): boolean {
  return report.status === "open" && (report.severity === "critical" || report.severity === "high");
}

/** Open reports first, then the most serious, then the one reported earliest. */
export function sortReports(reports: readonly ErrorReport[]): ErrorReport[] {
  return [...reports].sort((a, b) => {
    if (a.status !== b.status) {
      return ERROR_REPORT_STATUSES.indexOf(a.status) - ERROR_REPORT_STATUSES.indexOf(b.status);
    }
    if (a.severity !== b.severity) {
      return ERROR_SEVERITIES.indexOf(a.severity) - ERROR_SEVERITIES.indexOf(b.severity);
    }
    return Date.parse(a.reportedAt) - Date.parse(b.reportedAt);
  });
}

export function reportCounts(reports: readonly ErrorReport[]): ErrorReportCounts {
  return {
    total: reports.length,
    open: reports.filter((report) => report.status === "open").length,
    urgent: reports.filter(isUrgent).length,
    resolved: reports.filter((report) => report.status === "resolved").length,
  };
}

import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/** The file format a compliance report is generated in. */
export type ReportFormat = "pdf" | "xlsx" | "csv";

/** Where a report's generation stands. */
export type ReportStatus = "ready" | "generating" | "failed";

export const REPORT_FORMATS: readonly ReportFormat[] = ["pdf", "xlsx", "csv"];
export const REPORT_STATUSES: readonly ReportStatus[] = ["ready", "generating", "failed"];

/** One generated (or generating) report. */
export interface ReportItem {
  id: string;
  name: string;
  format: ReportFormat;
  status: ReportStatus;
  /** The instant generation was requested or finished. */
  generatedAt: string;
  /** The file size as the service words it, such as "1.2 MB". */
  size: string;
  /** The download address once the file exists, otherwise null. */
  url: string | null;
}

/** The figures in the summary row. */
export interface ReportCounts {
  total: number;
  ready: number;
  generating: number;
}

const FORMAT_LABEL: Readonly<Record<ReportFormat, MessageKey>> = {
  pdf: "reports.format.pdf",
  xlsx: "reports.format.xlsx",
  csv: "reports.format.csv",
};

const STATUS_LABEL: Readonly<Record<ReportStatus, MessageKey>> = {
  ready: "reports.status.ready",
  generating: "reports.status.generating",
  failed: "reports.status.failed",
};

const STATUS_TONE: Readonly<Record<ReportStatus, Tone>> = {
  ready: "success",
  generating: "warning",
  failed: "danger",
};

export function reportFormatLabel(format: ReportFormat): string {
  return t(FORMAT_LABEL[format]);
}

export function reportStatusLabel(status: ReportStatus): string {
  return t(STATUS_LABEL[status]);
}

export function reportStatusTone(status: ReportStatus): Tone {
  return STATUS_TONE[status];
}

export function reportFormatOptions(): SelectOption[] {
  return REPORT_FORMATS.map((value) => ({ value, label: reportFormatLabel(value) }));
}

export function reportStatusOptions(): SelectOption[] {
  return REPORT_STATUSES.map((value) => ({ value, label: reportStatusLabel(value) }));
}

/**
 * Where a report can be downloaded from: only a ready report with an http or https address;
 * anything else is not offered as a link.
 */
export function downloadUrl(report: ReportItem): string | null {
  if (report.status !== "ready" || report.url === null) return null;
  try {
    const url = new URL(report.url);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function reportCounts(reports: readonly ReportItem[]): ReportCounts {
  return {
    total: reports.length,
    ready: reports.filter((report) => report.status === "ready").length,
    generating: reports.filter((report) => report.status === "generating").length,
  };
}

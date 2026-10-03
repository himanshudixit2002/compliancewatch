import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  reportCounts,
  reportStatusLabel,
  reportStatusOptions,
  reportStatusTone,
  severityLabel,
  severityOptions,
  severityTone,
  sortReports,
  type ErrorReport,
} from "../model/error-reports";
import type { ReportRow } from "./report-filters";
import { ReportsTable } from "./reports-table";

export interface AdminErrorReportsViewProps {
  reports: readonly ErrorReport[];
  /** Where an analyst reads one report; without it the titles are not links. */
  hrefFor?: (reportId: string) => Route;
}

function reportRow(report: ErrorReport, hrefFor?: (reportId: string) => Route): ReportRow {
  return {
    id: report.id,
    title: report.title,
    message: report.message,
    subject: report.subject,
    href: hrefFor === undefined ? null : hrefFor(report.id),
    severity: report.severity,
    severityLabel: severityLabel(report.severity),
    severityTone: severityTone(report.severity),
    status: report.status,
    statusLabel: reportStatusLabel(report.status),
    statusTone: reportStatusTone(report.status),
    reportedLabel: formatDateTime(report.reportedAt),
  };
}

/**
 * The reported errors: how many there are, how many are open and how many of those are critical
 * or high, then the reports with their filters, open and most serious first, or an empty state
 * when nobody has reported an error.
 */
export function AdminErrorReportsView({ reports, hrefFor }: AdminErrorReportsViewProps) {
  const counts = reportCounts(reports);
  return (
    <div data-slot="admin-error-reports" className="flex flex-col gap-6">
      <PageHeader title={t("adminErrorReports.title")} description={t("adminErrorReports.intro")} />
      {reports.length === 0 ? (
        <EmptyState
          title={t("adminErrorReports.empty.title")}
          body={t("adminErrorReports.empty.body")}
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminErrorReports.stat.total")} value={counts.total} tone="info" />
            <StatCard
              label={t("adminErrorReports.stat.open")}
              value={counts.open}
              tone={counts.open > 0 ? "warning" : "neutral"}
            />
            <StatCard
              label={t("adminErrorReports.stat.urgent")}
              value={counts.urgent}
              tone={counts.urgent > 0 ? "danger" : "neutral"}
            />
            <StatCard
              label={t("adminErrorReports.stat.resolved")}
              value={counts.resolved}
              tone="success"
            />
          </div>
          <ReportsTable
            rows={sortReports(reports).map((report) => reportRow(report, hrefFor))}
            severityOptions={severityOptions()}
            statusOptions={reportStatusOptions()}
          />
        </>
      )}
    </div>
  );
}

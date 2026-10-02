import type { Route } from "next";
import Link from "next/link";
import { Button, EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  downloadUrl,
  reportCounts,
  reportFormatLabel,
  reportFormatOptions,
  reportStatusLabel,
  reportStatusOptions,
  reportStatusTone,
  type ReportItem,
} from "../model/reports";
import type { ReportRow } from "./report-filters";
import { ReportsTable } from "./reports-table";

export interface ReportsViewProps {
  reports: readonly ReportItem[];
  /** The page that starts a new report, or null while generating is not offered. */
  generateHref: Route | null;
}

function reportRow(report: ReportItem): ReportRow {
  return {
    id: report.id,
    name: report.name,
    format: report.format,
    formatLabel: reportFormatLabel(report.format),
    status: report.status,
    statusLabel: reportStatusLabel(report.status),
    statusTone: reportStatusTone(report.status),
    generatedAt: formatDateTime(report.generatedAt),
    size: report.size,
    downloadUrl: downloadUrl(report),
  };
}

/**
 * The compliance reports of an owner or a CA firm: how many exist, are ready and are still
 * generating, then the filterable table, or an empty state before the first report.
 */
export function ReportsView({ reports, generateHref }: ReportsViewProps) {
  const counts = reportCounts(reports);
  const generate =
    generateHref === null ? null : (
      <Button asChild>
        <Link href={generateHref}>{t("reports.generate")}</Link>
      </Button>
    );
  return (
    <div data-slot="reports" className="flex flex-col gap-6">
      <PageHeader
        title={t("reports.title")}
        description={t("reports.description")}
        actions={generate}
      />
      {reports.length === 0 ? (
        <EmptyState
          title={t("reports.empty.title")}
          body={t("reports.empty.body")}
          action={generate}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label={t("reports.stat.total")} value={counts.total} />
            <StatCard label={t("reports.stat.ready")} value={counts.ready} tone="success" />
            <StatCard
              label={t("reports.stat.generating")}
              value={counts.generating}
              tone="warning"
            />
          </div>
          <ReportsTable
            rows={reports.map(reportRow)}
            formatOptions={reportFormatOptions()}
            statusOptions={reportStatusOptions()}
          />
        </>
      )}
    </div>
  );
}

import {
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  formatShare,
  metricStanding,
  qualitySummary,
  standingLabel,
  standingTone,
  type QualityMetric,
} from "../model/quality";

export interface SystemQualityViewProps {
  metrics: readonly QualityMetric[];
  /** When the latest evaluation run finished, an ISO instant; null before the first. */
  measuredAt: string | null;
}

function MetricRow({ metric }: { metric: QualityMetric }) {
  const standing = metricStanding(metric);
  return (
    <TableRow data-metric={metric.id}>
      <TableCell className="whitespace-normal">
        <span className="block font-medium text-fg">{metric.name}</span>
        <span className="block text-xs text-fg-muted">{metric.description}</span>
      </TableCell>
      <TableCell className="font-medium text-fg">
        {metric.value === null ? standingLabel("unmeasured") : formatShare(metric.value)}
      </TableCell>
      <TableCell className="text-fg-muted">
        {t("systemQuality.target", { target: formatShare(metric.target) })}
      </TableCell>
      <TableCell>
        <StatusChip
          status={standing}
          tone={standingTone(standing)}
          label={standingLabel(standing)}
        />
      </TableCell>
    </TableRow>
  );
}

/**
 * The quality numbers page: how many measures meet their target, then each measure with how it
 * is measured, its latest value, its target and where it stands, or an empty state before the
 * first evaluation run.
 */
export function SystemQualityView({ metrics, measuredAt }: SystemQualityViewProps) {
  const summary = qualitySummary(metrics);
  return (
    <div data-slot="system-quality" className="flex flex-col gap-6">
      <PageHeader
        title={t("systemQuality.title")}
        description={
          measuredAt === null
            ? t("systemQuality.description")
            : t("systemQuality.descriptionMeasured", { date: formatDateTime(measuredAt) })
        }
      />
      {metrics.length === 0 ? (
        <EmptyState title={t("systemQuality.empty.title")} body={t("systemQuality.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("systemQuality.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("systemQuality.stat.meets")} value={summary.meets} tone="success" />
            <StatCard
              label={t("systemQuality.stat.below")}
              value={summary.below}
              tone={summary.below > 0 ? "danger" : "neutral"}
            />
            <StatCard label={t("systemQuality.stat.unmeasured")} value={summary.unmeasured} />
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("systemQuality.caption")}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("systemQuality.column.measure")}</TableHead>
                <TableHead>{t("systemQuality.column.latest")}</TableHead>
                <TableHead>{t("systemQuality.column.target")}</TableHead>
                <TableHead>{t("systemQuality.column.standing")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {metrics.map((metric) => (
                <MetricRow key={metric.id} metric={metric} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}

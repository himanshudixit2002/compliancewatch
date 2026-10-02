import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  likelihoodText,
  riskCounts,
  riskSeverityLabel,
  riskSeverityTone,
  riskStatusLabel,
  riskStatusTabs,
  riskStatusTone,
  type RiskItem,
} from "../model/risk";
import type { RiskRow } from "./risk-filters";
import { RiskTable } from "./risk-table";

export interface RiskViewProps {
  risks: readonly RiskItem[];
  /** The page of one risk. */
  hrefFor: (riskId: string) => Route;
}

function riskRow(risk: RiskItem, hrefFor: (riskId: string) => Route): RiskRow {
  return {
    id: risk.id,
    title: risk.title,
    description: risk.description,
    href: hrefFor(risk.id),
    severityLabel: riskSeverityLabel(risk.severity),
    severityTone: riskSeverityTone(risk.severity),
    status: risk.status,
    statusLabel: riskStatusLabel(risk.status),
    statusTone: riskStatusTone(risk.status),
    likelihood: likelihoodText(risk.likelihood),
    identifiedAt: formatDate(risk.identifiedAt),
    owner: risk.owner,
  };
}

/**
 * A business's risk register: how many risks there are, how many are high or medium severity
 * and how many are mitigated, then the register under status tabs, or an empty state.
 */
export function RiskView({ risks, hrefFor }: RiskViewProps) {
  const counts = riskCounts(risks);
  return (
    <div data-slot="risk" className="flex flex-col gap-6">
      <PageHeader title={t("risk.title")} description={t("risk.description")} />
      {risks.length === 0 ? (
        <EmptyState title={t("risk.empty.title")} body={t("risk.empty.body")} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("risk.stat.total")} value={counts.total} />
            <StatCard label={t("risk.stat.high")} value={counts.high} tone="danger" />
            <StatCard label={t("risk.stat.medium")} value={counts.medium} tone="warning" />
            <StatCard label={t("risk.stat.mitigated")} value={counts.mitigated} tone="success" />
          </div>
          <RiskTable
            rows={risks.map((risk) => riskRow(risk, hrefFor))}
            statusTabs={riskStatusTabs()}
          />
        </>
      )}
    </div>
  );
}

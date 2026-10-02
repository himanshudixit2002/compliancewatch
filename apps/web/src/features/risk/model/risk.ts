import type { RiskStatus, RiskSeverity } from "@/entities/risk/types";
import { t } from "@/shared/i18n";

export interface RiskView {
  businessId: string;
  risks: RiskItem[];
  totalCount: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  mitigatedCount: number;
  filter: "all" | RiskStatus;
  sort: "severity" | "identified" | "likelihood";
}

export interface RiskItem {
  id: string;
  title: string;
  description: string;
  severity: RiskSeverity;
  status: RiskStatus;
  likelihood: number;
  mitigation: string;
  identifiedAt: string;
  owner: string;
  obligationIds: string[];
}

export function emptyRiskView(businessId: string): RiskView {
  return {
    businessId,
    risks: [],
    totalCount: 0,
    highCount: 0,
    mediumCount: 0,
    lowCount: 0,
    mitigatedCount: 0,
    filter: "all",
    sort: "severity",
  };
}

export function riskSeverityLabel(severity: RiskSeverity): string {
  return t(`risk.severity.${severity}`);
}

export function riskStatusLabel(status: RiskStatus): string {
  return t(`risk.status.${status}`);
}

export function formatRiskDate(date: string): string {
  return new Date(date).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

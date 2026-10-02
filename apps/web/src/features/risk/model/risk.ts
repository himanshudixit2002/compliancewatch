import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/** How much harm a risk would do to the business if it happened. */
export type RiskSeverity = "high" | "medium" | "low";

/** Where a risk stands in the register. */
export type RiskStatus = "active" | "mitigated" | "closed";

export const RISK_STATUSES: readonly RiskStatus[] = ["active", "mitigated", "closed"];

/** One entry in a business's risk register. */
export interface RiskItem {
  id: string;
  title: string;
  description: string;
  severity: RiskSeverity;
  status: RiskStatus;
  /** The chance it happens, as a whole percentage from 0 to 100. */
  likelihood: number;
  /** Date key (YYYY-MM-DD) or instant when the risk was identified. */
  identifiedAt: string;
  owner: string;
}

/** The figures in the summary row. */
export interface RiskCounts {
  total: number;
  high: number;
  medium: number;
  mitigated: number;
}

const SEVERITY_LABEL: Readonly<Record<RiskSeverity, MessageKey>> = {
  high: "risk.severity.high",
  medium: "risk.severity.medium",
  low: "risk.severity.low",
};

const SEVERITY_TONE: Readonly<Record<RiskSeverity, Tone>> = {
  high: "danger",
  medium: "warning",
  low: "info",
};

const STATUS_LABEL: Readonly<Record<RiskStatus, MessageKey>> = {
  active: "risk.status.active",
  mitigated: "risk.status.mitigated",
  closed: "risk.status.closed",
};

const STATUS_TONE: Readonly<Record<RiskStatus, Tone>> = {
  active: "danger",
  mitigated: "success",
  closed: "neutral",
};

export function riskSeverityLabel(severity: RiskSeverity): string {
  return t(SEVERITY_LABEL[severity]);
}

export function riskSeverityTone(severity: RiskSeverity): Tone {
  return SEVERITY_TONE[severity];
}

export function riskStatusLabel(status: RiskStatus): string {
  return t(STATUS_LABEL[status]);
}

export function riskStatusTone(status: RiskStatus): Tone {
  return STATUS_TONE[status];
}

/** "40%", with the value kept within 0 to 100 and rounded to a whole number. */
export function likelihoodText(likelihood: number): string {
  return t("risk.likelihood", { percent: Math.round(Math.min(100, Math.max(0, likelihood))) });
}

export function riskStatusTabs(): SelectOption[] {
  return RISK_STATUSES.map((value) => ({ value, label: riskStatusLabel(value) }));
}

export function riskCounts(risks: readonly RiskItem[]): RiskCounts {
  return {
    total: risks.length,
    high: risks.filter((risk) => risk.severity === "high").length,
    medium: risks.filter((risk) => risk.severity === "medium").length,
    mitigated: risks.filter((risk) => risk.status === "mitigated").length,
  };
}

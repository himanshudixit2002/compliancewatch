import type { obligation } from "@compliancewatch/contracts/openapi";
import { t } from "@/shared/i18n";

type ObligationStatus = obligation.components["schemas"]["ObligationStatus"];

export interface ObligationView {
  obligations: Obligation[];
  businessId: string;
  totalCount: number;
  openCount: number;
  inProgressCount: number;
  doneCount: number;
  overdueCount: number;
  filter: ObligationFilter;
  sort: ObligationSort;
}

export interface Obligation {
  id: string;
  businessId: string;
  title: string;
  description: string;
  status: ObligationStatus;
  dueAt: string | null;
  evidenceType: string;
  steps: string[];
  ruleVersionId: string;
  decisionId: string;
  closedAt: string | null;
  closedReason: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  periodLabel: string | null;
}

export type ObligationFilter = "all" | ObligationStatus;
export type ObligationSort = "due" | "status" | "created" | "title";

export function emptyObligations(businessId: string): ObligationView {
  return {
    obligations: [],
    businessId,
    totalCount: 0,
    openCount: 0,
    inProgressCount: 0,
    doneCount: 0,
    overdueCount: 0,
    filter: "all",
    sort: "due",
  };
}

export function obligationStatusLabel(status: ObligationStatus): string {
  return t(`obligation.status.${status}`);
}

export function obligationStatusTone(status: ObligationStatus): "danger" | "warning" | "success" | "info" | "neutral" {
  switch (status) {
    case "open":
      return "info";
    case "in_progress":
      return "warning";
    case "done":
      return "success";
    case "waived":
      return "neutral";
    case "closed_not_applicable":
      return "neutral";
    default:
      return "neutral";
  }
}

export function isObligationOverdue(obligation: Obligation): boolean {
  if (!obligation.dueAt || obligation.status === "done" || obligation.status === "waived" || obligation.status === "closed_not_applicable") {
    return false;
  }
  return new Date(obligation.dueAt) < new Date();
}

export function formatObligationDate(date: string | null): string {
  if (!date) return "—";
  return new Date(date).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

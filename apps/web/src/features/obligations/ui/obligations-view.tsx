import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { StatCard } from "@/shared/ui/stat-card";
import {
  dueDateText,
  duePhrase,
  evidenceTypeText,
  isObligationOverdue,
  obligationCounts,
  obligationStatusLabel,
  obligationStatusOptions,
  obligationStatusTone,
  periodText,
  type Obligation,
} from "../model/obligations";
import type { ObligationRow } from "./obligation-rows";
import { ObligationsTable } from "./obligations-table";

export interface ObligationsViewProps {
  /** The business's obligations, earliest due date first as the service lists them. */
  obligations: readonly Obligation[];
  /** The page of one obligation. */
  hrefFor: (obligationId: string) => Route;
  /** Now, for the due dates; tests pass a fixed instant. */
  now?: Date;
}

function obligationRow(
  item: Obligation,
  hrefFor: (obligationId: string) => Route,
  now: Date,
): ObligationRow {
  return {
    id: item.id,
    title: item.title,
    href: hrefFor(item.id),
    period: periodText(item),
    status: item.status,
    statusLabel: obligationStatusLabel(item.status),
    statusTone: obligationStatusTone(item.status),
    due: dueDateText(item),
    dueNote: duePhrase(item, now),
    overdue: isObligationOverdue(item, now),
    evidence: evidenceTypeText(item.evidenceType),
  };
}

/**
 * A business's obligations: how many are open, in progress, overdue and done, then the list
 * with each one's status, due date and the evidence it needs, or an empty state.
 */
export function ObligationsView({ obligations, hrefFor, now = new Date() }: ObligationsViewProps) {
  const counts = obligationCounts(obligations, now);
  return (
    <div data-slot="obligations" className="flex flex-col gap-6">
      <PageHeader title={t("obligations.title")} description={t("obligations.description")} />
      {obligations.length === 0 ? (
        <EmptyState title={t("obligations.empty.title")} body={t("obligations.empty.body")} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard label={t("obligations.stat.total")} value={counts.total} />
            <StatCard label={t("obligations.stat.open")} value={counts.open} tone="info" />
            <StatCard
              label={t("obligations.stat.inProgress")}
              value={counts.inProgress}
              tone="warning"
            />
            <StatCard
              label={t("obligations.stat.overdue")}
              value={counts.overdue}
              tone={counts.overdue > 0 ? "danger" : "neutral"}
            />
            <StatCard label={t("obligations.stat.done")} value={counts.done} tone="success" />
          </div>
          <ObligationsTable
            rows={obligations.map((item) => obligationRow(item, hrefFor, now))}
            statusOptions={obligationStatusOptions()}
          />
        </>
      )}
    </div>
  );
}

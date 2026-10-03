import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime, istDateKey } from "@/shared/lib/dates";
import {
  auditCategory,
  auditCategoryLabel,
  auditCategoryOptions,
  describeChange,
  newestFirst,
  type AuditEvent,
} from "../model/audit";
import type { AuditRow } from "./audit-filters";
import { AuditTable } from "./audit-table";

export interface AuditViewProps {
  events: readonly AuditEvent[];
}

function auditRow(event: AuditEvent): AuditRow {
  const category = auditCategory(event.action);
  return {
    id: event.id,
    actor: event.actor,
    action: event.action,
    category,
    categoryLabel: auditCategoryLabel(category),
    subjectType: event.subjectType,
    subjectId: event.subjectId,
    changes: event.changes.map(describeChange),
    at: formatDateTime(event.at),
    day: istDateKey(new Date(event.at)),
  };
}

/**
 * The audit trail for the regulatory team: every recorded event, newest first, with who acted,
 * what they did, to which record and what changed, under a search, a category and a date range;
 * or an empty state before anything is recorded.
 */
export function AuditView({ events }: AuditViewProps) {
  return (
    <div data-slot="admin-audit" className="flex flex-col gap-6">
      <PageHeader title={t("adminAudit.title")} description={t("adminAudit.description")} />
      {events.length === 0 ? (
        <EmptyState title={t("adminAudit.empty.title")} body={t("adminAudit.empty.body")} />
      ) : (
        <AuditTable
          rows={newestFirst(events).map(auditRow)}
          categoryOptions={auditCategoryOptions()}
        />
      )}
    </div>
  );
}

import type { SelectOption } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The audit trail's model: the platform's insert-only audit events (actor, action, subject,
 * before and after, and when; guide section 6.2) as `GET /v1/identity/audit` will return them,
 * grouped into categories by the domain each action belongs to.
 */
export type AuditCategory = "user" | "tenant" | "obligation" | "rule" | "other";

export const AUDIT_CATEGORIES: readonly AuditCategory[] = [
  "user",
  "tenant",
  "obligation",
  "rule",
  "other",
];

/** One field an event changed: set (nothing before), cleared (nothing after) or updated. */
export type AuditChange =
  | { field: string; before: null; after: string }
  | { field: string; before: string; after: null }
  | { field: string; before: string; after: string };

export interface AuditEvent {
  id: string;
  /** Who acted: a person's display name, or the service that acted on its own. */
  actor: string;
  /** What happened, as the service records it: "user.disabled", "rule.published". */
  action: string;
  /** The kind of record acted on ("user", "rule_version", "obligation"). */
  subjectType: string;
  subjectId: string;
  /** The fields the action changed; empty when it changed none, such as an export. */
  changes: readonly AuditChange[];
  /** When it happened, an ISO instant. */
  at: string;
}

const CATEGORY_LABEL: Readonly<Record<AuditCategory, MessageKey>> = {
  user: "adminAudit.category.user",
  tenant: "adminAudit.category.tenant",
  obligation: "adminAudit.category.obligation",
  rule: "adminAudit.category.rule",
  other: "adminAudit.category.other",
};

function isAuditCategory(value: string): value is AuditCategory {
  return (AUDIT_CATEGORIES as readonly string[]).includes(value);
}

/** The category of an action, from the domain before its first dot: "rule.published" is a rule. */
export function auditCategory(action: string): AuditCategory {
  const dot = action.indexOf(".");
  const domain = (dot === -1 ? action : action.slice(0, dot)).toLowerCase();
  return isAuditCategory(domain) ? domain : "other";
}

export function auditCategoryLabel(category: AuditCategory): string {
  return t(CATEGORY_LABEL[category]);
}

export function auditCategoryOptions(): SelectOption[] {
  return AUDIT_CATEGORIES.map((value) => ({ value, label: auditCategoryLabel(value) }));
}

/** One change in words: "status: active → disabled", "region set to …" or "phone cleared …". */
export function describeChange(change: AuditChange): string {
  if (change.before === null) {
    return t("adminAudit.change.set", { field: change.field, after: change.after });
  }
  if (change.after === null) {
    return t("adminAudit.change.cleared", { field: change.field, before: change.before });
  }
  return t("adminAudit.change.updated", {
    field: change.field,
    before: change.before,
    after: change.after,
  });
}

/** The events newest first; events at the same instant keep their order. */
export function newestFirst(events: readonly AuditEvent[]): AuditEvent[] {
  return [...events].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

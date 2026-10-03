/**
 * The audit trail screen's model: each log entry the platform records, the view the table
 * and filters consume, and the helpers that group actions by their domain.
 */

/** A single row in the audit log table. */
export interface AuditEntry {
  /** Stable id from the audit store. */
  id: string;
  /** The display name of the actor at the time of the action. */
  actorName: string;
  /** The verb describing what happened (e.g. "user.disabled", "rule.published"). */
  action: string;
  /** The entity kind the action touched (user, tenant, obligation, rule …). */
  targetType: string;
  /** The specific entity id, if any. */
  targetId: string;
  /** Human-readable summary of the changes made. */
  changes: string;
  /** The IP address recorded at action time; empty when not available. */
  ipAddress: string;
  /** ISO instant the entry was written. */
  createdAt: string;
}

/** The date-pair the user has typed into the from / to inputs. */
export interface DateRange {
  from: string;
  to: string;
}

/** The full view backing the audit log page. */
export interface AuditView {
  entries: readonly AuditEntry[];
  /** Total entries across all pages, for pagination. */
  totalCount: number;
  /** The active action-category tab, if any. */
  filter: ActionCategory | null;
  /** The selected date range, if any. */
  dateRange: DateRange;
}

/** The four high-level domains used for the action-category tabs, plus the catch-all. */
export type ActionCategory = "user" | "tenant" | "obligation" | "rule" | "other";

/** Tab items for the action-category filter. */
export const CATEGORY_TABS: ReadonlyArray<{ value: ActionCategory; label: string }> = [
  { value: "other", label: "Other" },
  { value: "user", label: "User" },
  { value: "tenant", label: "Tenant" },
  { value: "obligation", label: "Obligation" },
  { value: "rule", label: "Rule" },
];

/** The category that owns a raw action string such as "user.disabled". */
export function actionCategory(action: string): ActionCategory {
  const prefix = action.split(".")[0]?.toLowerCase();
  switch (prefix) {
    case "user":
      return "user";
    case "tenant":
      return "tenant";
    case "obligation":
      return "obligation";
    case "rule":
      return "rule";
    default:
      return "other";
  }
}

/** A human-readable label for an action. Falls back to the raw action string. */
export function actionLabel(action: string): string {
  // Backend action strings are used as-is; i18n labels arrive when the Hindi
  // translation file is added.  The fallback keeps the UI readable until then.
  return action;
}

/** An empty view the page renders before any data has loaded. */
export function emptyAudit(): AuditView {
  return {
    entries: [],
    totalCount: 0,
    filter: null,
    dateRange: { from: "", to: "" },
  };
}
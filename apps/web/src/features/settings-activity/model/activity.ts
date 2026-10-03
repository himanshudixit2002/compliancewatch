/**
 * The activity log screen's model: entries from the audit trail showing who changed what in the
 * account. Each entry records the action taken, when it happened, and from which IP address.
 */

export interface ActivityEntry {
  id: string;
  action: string;
  description: string;
  /** ISO instant. */
  timestamp: string;
  ipAddress: string;
}

export interface ActivityView {
  entries: readonly ActivityEntry[];
  totalCount: number;
}

export function emptyActivity(): ActivityView {
  return { entries: [], totalCount: 0 };
}

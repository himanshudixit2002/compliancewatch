import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/**
 * A notifications table row with every label already resolved, so the client table needs no
 * model import and no function props across the server boundary.
 */
export interface NotificationRow {
  id: string;
  subject: string;
  href: Route;
  channelLabel: string;
  /** The raw delivery state, kept on the chip as data-status. */
  state: string;
  stateLabel: string;
  tone: Tone;
  recipient: string;
  sentLabel: string;
}

/**
 * The rows whose subject, recipient, channel or state contain the query, ignoring case and
 * surrounding spaces; a blank query keeps every row.
 */
export function filterNotificationRows(
  rows: readonly NotificationRow[],
  query: string,
): readonly NotificationRow[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return rows;
  return rows.filter((row) =>
    [row.subject, row.recipient, row.channelLabel, row.stateLabel].some((text) =>
      text.toLowerCase().includes(needle),
    ),
  );
}

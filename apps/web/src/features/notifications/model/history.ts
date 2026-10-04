import { withQuery } from "@/shared/lib/url";
import type { HistoryFilter, NotificationDetailView, NotificationRow } from "./notifications";

/**
 * The reminders pages as they render: the business, a page of its notifications with the way to
 * the next page and back to the newest, or one notification with the way back to the list.
 */
export interface BusinessRef {
  id: string;
  name: string;
  pan: string;
}

export interface RemindersView {
  business: BusinessRef;
  rows: NotificationRow[];
  filter: HistoryFilter;
  /** The next page, or null on the last. */
  nextHref: string | null;
  /** The newest page, when this is a later one; null otherwise. */
  firstHref: string | null;
}

export interface ReminderView {
  business: BusinessRef;
  detail: NotificationDetailView;
  listHref: string;
  /** The notification this one falls back from, under the same business. */
  fallbackHref: string | null;
}

/** The next page after the cursor the service returned, and the newest page from a later one. */
export function historyHrefs(
  listHref: string,
  filter: HistoryFilter,
  nextCursor: string | null,
  keep: Readonly<Record<string, string>> = {},
): { nextHref: string | null; firstHref: string | null } {
  return {
    nextHref:
      nextCursor === null
        ? null
        : withQuery(listHref, { ...keep, state: filter.state, cursor: nextCursor }),
    firstHref:
      filter.cursor === undefined ? null : withQuery(listHref, { ...keep, state: filter.state }),
  };
}

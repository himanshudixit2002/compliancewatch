import type { Tone } from "@compliancewatch/ui";
import type { ListedObligation, ObligationStatus } from "@/entities/obligation/types";
import { t } from "@/shared/i18n";
import { daysBetween, formatDate, isDateKey } from "@/shared/lib/dates";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import {
  ALL_STATUSES,
  dueDateText,
  duePhrase,
  dueDay,
  isObligationOverdue,
  isStatusFilter,
  obligationStatusLabel,
  obligationStatusTone,
  periodText,
  reviewState,
  type StatusFilter,
} from "./obligations";

/**
 * The obligation list of a business: the obligations of its legal entity and of each of its
 * registrations (the service keeps a GSTIN's returns for its registration), merged by due date,
 * a page at a time, with a status filter and a due window in the address.
 *
 * Each node's list is the public API's `GET /v1/businesses/{node}/obligations`, ordered by due
 * date (the ones without one last), then by id, and paged with the service's own cursor. The
 * merged page cannot carry one cursor per node in the address, so it carries the key of its last
 * row instead (`after`): the next page asks each node again from that row's due day in India
 * (`due_from`) and drops the rows up to the key. A row without a due date sorts last, so a key
 * without one asks each node from its start; that walk only happens on a list whose dated rows
 * are all behind it.
 */
export const LIST_PAGE_SIZE = 25;

/** The longest due window the service lists, in days, both ends included (MAX_WINDOW_DAYS). */
export const MAX_WINDOW_DAYS = 366;

/** Where a merged page ends: the last row's due instant (null for none) and its id. */
export interface ListKey {
  dueAt: string | null;
  id: string;
}

export interface ListFilter {
  status: StatusFilter;
  /** Date keys in India, both ends included; null for an open end. */
  from: string | null;
  to: string | null;
  /** The page starts after this row; null for the first page. */
  after: ListKey | null;
}

export type FilterField = "from" | "to";

export interface FilterRead {
  filter: ListFilter;
  /** What was typed, for the form to show back, valid or not. */
  typed: { from: string; to: string };
  /** Field paths to messages; empty when the filter can be asked. */
  errors: Readonly<Partial<Record<FilterField, string>>>;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The base64url JSON `{"d": dueAt | null, "i": id}` of a key (ASCII only: ids and instants). */
export function encodeListKey(key: ListKey): string {
  const json = JSON.stringify({ d: key.dueAt, i: key.id });
  return btoa(json).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): string {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  return atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
}

/** The key an `after` value holds, or null for anything this list did not write. */
export function decodeListKey(value: string | undefined): ListKey | null {
  if (value === undefined || value === "" || value.length > 512) return null;
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const parsed: unknown = JSON.parse(fromBase64Url(value));
    if (typeof parsed !== "object" || parsed === null) return null;
    const { d, i } = parsed as { d?: unknown; i?: unknown };
    if (typeof i !== "string" || !isUuid(i)) return null;
    if (d === null) return { dueAt: null, id: i };
    if (typeof d !== "string" || Number.isNaN(Date.parse(d))) return null;
    return { dueAt: d, id: i };
  } catch {
    return null;
  }
}

/**
 * The filter in the address: `status` (every status unless one of the filter's values), `from`
 * and `to` (date keys) and `after`. A window the service would refuse is reported on its field
 * rather than sent: a date that is not one, an end before the start, or more than 366 days.
 */
export function readListFilter(query: Query): FilterRead {
  const status = first(query.status);
  const from = (first(query.from) ?? "").trim();
  const to = (first(query.to) ?? "").trim();
  const errors: Partial<Record<FilterField, string>> = {};
  if (from !== "" && !isDateKey(from)) errors.from = t("obligations.window.notADate");
  if (to !== "" && !isDateKey(to)) errors.to = t("obligations.window.notADate");
  if (errors.from === undefined && errors.to === undefined && from !== "" && to !== "") {
    const days = daysBetween(from, to) + 1;
    if (days < 1) {
      errors.to = t("obligations.window.endBeforeStart");
    } else if (days > MAX_WINDOW_DAYS) {
      errors.to = t("obligations.window.tooLong", { days, max: MAX_WINDOW_DAYS });
    }
  }
  return {
    filter: {
      status: status !== undefined && isStatusFilter(status) ? status : ALL_STATUSES,
      from: from !== "" && errors.from === undefined ? from : null,
      to: to !== "" && errors.to === undefined ? to : null,
      after: decodeListKey(first(query.after)),
    },
    typed: { from, to },
    errors,
  };
}

export function hasFilterErrors(read: FilterRead): boolean {
  return Object.keys(read.errors).length > 0;
}

/** The address of the list with a filter: the defaults are left out. */
export function listHref(
  pathname: string,
  filter: Pick<ListFilter, "status" | "from" | "to">,
  after?: ListKey,
): string {
  return withQuery(pathname, {
    status: filter.status === ALL_STATUSES ? undefined : filter.status,
    from: filter.from ?? undefined,
    to: filter.to ?? undefined,
    after: after === undefined ? undefined : encodeListKey(after),
  });
}

function instant(value: string): number {
  return Date.parse(value);
}

/** Due date first (the ones without one last), then id: the service's own order. */
export function compareByDue(a: ListKey, b: ListKey): number {
  if (a.dueAt !== b.dueAt) {
    if (a.dueAt === null) return 1;
    if (b.dueAt === null) return -1;
    const difference = instant(a.dueAt) - instant(b.dueAt);
    if (difference !== 0) return difference;
  }
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function isAfterKey(item: ListKey, key: ListKey | null): boolean {
  return key === null || compareByDue(item, key) > 0;
}

/**
 * The due window to ask each node for the page after `key`: from the key's due day in India (or
 * the filter's start, if later) to the filter's end. A key without a due date keeps the filter's
 * window, which has no end then: a window hides the rows without a due date.
 */
export function windowAfter(
  filter: Pick<ListFilter, "from" | "to">,
  key: ListKey | null,
): { from: string | null; to: string | null } {
  if (key === null || key.dueAt === null) return { from: filter.from, to: filter.to };
  const day = dueDay(key.dueAt);
  return { from: filter.from !== null && filter.from > day ? filter.from : day, to: filter.to };
}

export interface NodeRows<T extends ListKey> {
  /** The node's rows after the key, in the service's order. */
  items: readonly T[];
  /** True when the node holds rows after these. */
  more: boolean;
}

/**
 * The first `limit` rows of the nodes' rows merged in due order, and whether more follow. Each
 * node gives its rows after the key, at most `limit + 1` of them or all it has, so the first
 * `limit` merged rows are the list's next rows.
 */
export function mergeByDue<T extends ListKey>(
  nodes: readonly NodeRows<T>[],
  limit: number,
): { items: T[]; more: boolean } {
  const merged = nodes.flatMap((node) => node.items).sort(compareByDue);
  return {
    items: merged.slice(0, limit),
    more: merged.length > limit || nodes.some((node) => node.more),
  };
}

/** A node of the business as the list names it: its PAN or GSTIN with its name. */
export interface NamedNode {
  id: string;
  name: string;
}

/** One obligation, worded for the table. */
export interface ObligationRow {
  id: string;
  title: string;
  href: string;
  /** The node it is kept for, by its GSTIN or PAN; null when the business has one node. */
  node: string | null;
  period: string | null;
  status: ObligationStatus;
  statusLabel: string;
  statusTone: Tone;
  /** The due date in India, or that there is none. */
  due: string;
  /** How the due day relates to today; null once closed or without a due date. */
  dueNote: string | null;
  overdue: boolean;
  review: { label: string; tone: Tone; reviewed: boolean };
  citations: number;
}

export function obligationRow(
  item: ListedObligation,
  options: { href: string; nodes: readonly NamedNode[]; now?: Date },
): ObligationRow {
  const now = options.now ?? new Date();
  const node = options.nodes.find((candidate) => candidate.id === item.businessId);
  return {
    id: item.id,
    title: item.title,
    href: options.href,
    node: options.nodes.length > 1 ? (node?.name ?? t("obligations.unknownNode")) : null,
    period: periodText(item),
    status: item.status,
    statusLabel: obligationStatusLabel(item.status),
    statusTone: obligationStatusTone(item.status),
    due: dueDateText(item),
    dueNote: duePhrase(item, now),
    overdue: isObligationOverdue(item, now),
    review: reviewState(item.ruleVersion),
    citations: item.citations.length,
  };
}

/** "Due from 1 Jan 2026 to 31 Dec 2026", or the one end there is; null without a window. */
export function windowText(filter: Pick<ListFilter, "from" | "to">): string | null {
  if (filter.from !== null && filter.to !== null) {
    return t("obligations.window.between", {
      from: formatDate(filter.from),
      to: formatDate(filter.to),
    });
  }
  if (filter.from !== null)
    return t("obligations.window.fromOnly", { from: formatDate(filter.from) });
  if (filter.to !== null) return t("obligations.window.toOnly", { to: formatDate(filter.to) });
  return null;
}

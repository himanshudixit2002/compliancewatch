import "server-only";

import type { Business } from "@/entities/business/types";
import type { ListedObligation } from "@/entities/obligation/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import type { ClientContext } from "@/server/api/services";
import { err, ok, webError, type ApiError, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { calendarView, monthWindow, type CalendarMonth, type CalendarView } from "./model/calendar";
import { obligationPageView, whyView, type ObligationPageView, type WhyView } from "./model/detail";
import {
  LIST_PAGE_SIZE,
  decisionKey,
  hasFilterErrors,
  isAfterKey,
  listHref,
  mergeByDue,
  obligationRow,
  windowAfter,
  type FilterRead,
  type ListKey,
  type NamedNode,
  type NodeRows,
  type ObligationRow,
  type RowApplicability,
} from "./model/list";
import { dueDateText, duePhrase, statusesOf, type StatusFilter } from "./model/obligations";
import { obligationsGateway, type ObligationsGateway } from "./gateway";
import type { TeamMember } from "./ports";
import type { FirstObligationState } from "./ui/tracking-shared";

/**
 * The obligation screens' reads for the session's tenant. Each starts from the business (the
 * profile service says whether the tenant holds it, and lists its registrations): the
 * obligations are kept per node, so a page asks the entity and every registration and merges
 * them by due date. The profile service has no route that lists a registration's locations, so
 * an obligation kept for a location is not in these lists yet.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
  now?: Date;
}

export type QuerySession = NonNullable<ClientContext["session"]>;

/** The largest page the service serves; a whole month or a node's first rows fit in one. */
const SERVICE_PAGE = 200;

/** How many service pages one node may take for one of our pages before we stop and say so. */
const MAX_CALLS_PER_NODE = 5;

/** The business by its nodes, each named by its PAN or GSTIN with its name. */
export function namedNodes(business: Business): NamedNode[] {
  return [
    {
      id: business.id,
      name: t("business.node.entity", { key: business.pan, name: business.name }),
    },
    ...business.registrations.map((node) => ({
      id: node.id,
      name: t("business.node.registration", { key: node.key, name: node.name }),
    })),
  ];
}

export interface BusinessRef {
  id: string;
  name: string;
  pan: string;
}

function businessRef(business: Business): BusinessRef {
  return { id: business.id, name: business.name, pan: business.pan };
}

/** A node held more rows before the page's key than one page may walk past. */
function listTooLong(): ApiError {
  return webError("bad_request", "web-obligation-list-too-long", t("obligations.tooLong"));
}

/**
 * A node's rows after `key`: from the key's due day on (the service's window), dropping the rows
 * up to the key, following the node's own cursor until `limit + 1` rows or its end. The first
 * request asks for `limit + 1` rows, any later one for the service's largest page; a node that
 * still has rows to walk past after `MAX_CALLS_PER_NODE` requests is reported, never guessed.
 */
async function rowsAfter(
  gateway: ObligationsGateway,
  nodeId: string,
  query: {
    status: StatusFilter;
    from: string | null;
    to: string | null;
    key: ListKey | null;
    limit: number;
  },
): Promise<Result<NodeRows<ListedObligation>>> {
  const window = windowAfter(query, query.key);
  const rows: ListedObligation[] = [];
  let cursor: string | undefined;
  for (let calls = 0; calls < MAX_CALLS_PER_NODE; calls += 1) {
    const page = await gateway.list(nodeId, {
      statuses: statusesOf(query.status),
      dueFrom: window.from,
      dueTo: window.to,
      limit: calls === 0 ? Math.min(query.limit + 1, SERVICE_PAGE) : SERVICE_PAGE,
      ...(cursor === undefined ? {} : { cursor }),
    });
    if (!page.ok) return page;
    rows.push(...page.value.items.filter((item) => isAfterKey(item, query.key)));
    if (rows.length > query.limit) return ok({ items: rows, more: true });
    if (page.value.nextCursor === null) return ok({ items: rows, more: false });
    cursor = page.value.nextCursor;
  }
  return err(listTooLong());
}

/** The first error of several reads, or every value. */
function all<T>(results: readonly Result<T>[]): Result<T[]> {
  const values: T[] = [];
  for (const result of results) {
    if (!result.ok) return result;
    values.push(result.value);
  }
  return ok(values);
}

/**
 * The engine's latest decision of each row's rule version for its node, read once per pair on
 * the page (a monthly return's periods share one), in parallel; a failed read leaves its rows'
 * badge unknown rather than failing the list.
 */
async function rowDecisions(
  gateway: ObligationsGateway,
  items: readonly ListedObligation[],
): Promise<Map<string, RowApplicability>> {
  const pairs = new Map<string, ListedObligation>();
  for (const item of items) pairs.set(decisionKey(item), item);
  const entries = [...pairs.entries()];
  const read = await Promise.all(
    entries.map(([, item]) => gateway.latestDecision(item.businessId, item.ruleVersionId)),
  );
  return new Map(
    entries.map(([key], index): [string, RowApplicability] => {
      const decision = read[index];
      if (decision === undefined || !decision.ok) return [key, { state: "unknown" }];
      return [
        key,
        decision.value === null
          ? { state: "none" }
          : {
              state: "decided",
              result: decision.value.result,
              needsReview: decision.value.needsReview,
            },
      ];
    }),
  );
}

export interface ObligationListView {
  business: BusinessRef;
  /** How many nodes the list merges: the entity and its registrations. */
  nodes: number;
  read: FilterRead;
  rows: readonly ObligationRow[];
  /** True when the filter was asked; false while the form holds a window the service refuses. */
  asked: boolean;
  nextHref: string | null;
  firstHref: string | null;
}

export async function getObligationList(
  session: QuerySession,
  businessId: string,
  read: FilterRead,
  deps: QueryDeps = {},
): Promise<Result<ObligationListView>> {
  const gateway = obligationsGateway({ session, fetchImpl: deps.fetchImpl });
  const business = await gateway.business(businessId);
  if (!business.ok) return business;
  const pathname = hrefFor(screenById("owner.obligations"), { businessId });
  const nodes = namedNodes(business.value);
  const base = { business: businessRef(business.value), nodes: nodes.length, read };
  if (hasFilterErrors(read)) {
    return ok({ ...base, rows: [], asked: false, nextHref: null, firstHref: null });
  }
  const { filter } = read;
  const pages = all(
    await Promise.all(
      nodes.map((node) =>
        rowsAfter(gateway, node.id, { ...filter, key: filter.after, limit: LIST_PAGE_SIZE }),
      ),
    ),
  );
  if (!pages.ok) return pages;
  const merged = mergeByDue(pages.value, LIST_PAGE_SIZE);
  const detail = screenById("owner.obligation");
  const last = merged.items.at(-1);
  const decisions = await rowDecisions(gateway, merged.items);
  return ok({
    ...base,
    asked: true,
    rows: merged.items.map((item) =>
      obligationRow(item, {
        href: hrefFor(detail, { businessId, obligationId: item.id }),
        nodes,
        applicability: decisions.get(decisionKey(item)) ?? { state: "unknown" },
        ...(deps.now === undefined ? {} : { now: deps.now }),
      }),
    ),
    nextHref:
      merged.more && last !== undefined
        ? listHref(pathname, filter, { dueAt: last.dueAt, id: last.id })
        : null,
    firstHref: filter.after === null ? null : listHref(pathname, filter),
  });
}

export interface CalendarPageView {
  business: BusinessRef;
  calendar: CalendarView;
}

/** One month of the business's obligations by due day, every node's whole month. */
export async function getCalendar(
  session: QuerySession,
  businessId: string,
  month: CalendarMonth,
  deps: QueryDeps = {},
): Promise<Result<CalendarPageView>> {
  const gateway = obligationsGateway({ session, fetchImpl: deps.fetchImpl });
  const business = await gateway.business(businessId);
  if (!business.ok) return business;
  const window = monthWindow(month);
  const pages = all(
    await Promise.all(
      namedNodes(business.value).map((node) =>
        rowsAfter(gateway, node.id, {
          status: "all",
          from: window.from,
          to: window.to,
          key: null,
          limit: SERVICE_PAGE * MAX_CALLS_PER_NODE - 1,
        }),
      ),
    ),
  );
  if (!pages.ok) return pages;
  const detail = screenById("owner.obligation");
  const calendar = calendarView(
    month,
    pages.value.flatMap((node) => node.items),
    {
      hrefFor: (obligationId) => hrefFor(detail, { businessId, obligationId }),
      ...(deps.now === undefined ? {} : { now: deps.now }),
    },
  );
  return ok({
    business: businessRef(business.value),
    // A node holding more of the month than the read takes: the page says so.
    calendar: { ...calendar, cut: pages.value.some((node) => node.more) },
  });
}

/** Who an obligation can be given to: the tenant's users, or why the page offers an id field. */
export type AssigneeChoice =
  | { kind: "members"; members: readonly TeamMember[] }
  | { kind: "id"; reason: "role" | "unavailable" };

export interface ObligationDetailPageView {
  business: BusinessRef;
  obligation: ObligationPageView;
  assignee: AssigneeChoice;
  listHref: string;
}

function notThisBusiness(): ApiError {
  return webError("not_found", "web-obligation-not-found", t("obligation.notThisBusiness"));
}

/**
 * One obligation of the business: the obligation service's detail, checked to be kept for a
 * node of this business; then, side by side, the engine's latest decision for its node and rule
 * version, the text of each clause it cites and, for a tenant admin, the tenant's users. A
 * failure of those three is shown where it belongs on the page rather than failing the page.
 */
export async function getObligation(
  session: QuerySession,
  businessId: string,
  obligationId: string,
  options: { canListMembers: boolean },
  deps: QueryDeps = {},
): Promise<Result<ObligationDetailPageView>> {
  const gateway = obligationsGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, detail] = await Promise.all([
    gateway.business(businessId),
    gateway.detail(obligationId),
  ]);
  if (!business.ok) return business;
  if (!detail.ok) return detail;
  const nodes = namedNodes(business.value);
  const node = nodes.find((candidate) => candidate.id === detail.value.businessId);
  if (node === undefined) return err(notThisBusiness());

  const clauseIds = [...new Set(detail.value.citations.map((citation) => citation.clauseId))];
  const [decision, clauses, members] = await Promise.all([
    gateway.latestDecision(detail.value.businessId, detail.value.ruleVersionId),
    Promise.all(clauseIds.map((id) => gateway.clause(id))),
    options.canListMembers ? gateway.members() : Promise.resolve(null),
  ]);
  const clauseMap = new Map<string, ClauseDetail>();
  for (const clause of clauses) if (clause.ok) clauseMap.set(clause.value.clauseId, clause.value);
  const why: WhyView = decision.ok
    ? whyView(decision.value, detail.value.decisionId)
    : {
        state: "error",
        message: decision.error.message,
        correlationId: decision.error.requestId === "" ? null : decision.error.requestId,
      };
  return ok({
    business: businessRef(business.value),
    obligation: obligationPageView(detail.value, {
      node: node.name,
      clauses: clauseMap,
      why,
      viewerId: session.userId,
      ...(deps.now === undefined ? {} : { now: deps.now }),
    }),
    assignee:
      members === null
        ? { kind: "id", reason: "role" }
        : members.ok
          ? { kind: "members", members: members.value }
          : { kind: "id", reason: "unavailable" },
    listHref: hrefFor(screenById("owner.obligations"), { businessId }),
  });
}

/**
 * The business's first obligation by due date, across its nodes: one row of each node's list.
 * The poll asks this until one appears; a failure is reported, and the poll tries again.
 */
export async function findFirstObligation(
  session: QuerySession,
  businessId: string,
  deps: QueryDeps = {},
): Promise<FirstObligationState> {
  const gateway = obligationsGateway({ session, fetchImpl: deps.fetchImpl });
  const failed = (error: ApiError): FirstObligationState => ({
    status: "error",
    message: error.message,
    correlationId: error.requestId === "" ? null : error.requestId,
  });
  const business = await gateway.business(businessId);
  if (!business.ok) return failed(business.error);
  const pages = all(
    await Promise.all(
      namedNodes(business.value).map((node) =>
        gateway.list(node.id, { statuses: [], dueFrom: null, dueTo: null, limit: 1 }),
      ),
    ),
  );
  if (!pages.ok) return failed(pages.error);
  const first = mergeByDue(
    pages.value.map((page) => ({ items: page.items, more: false })),
    1,
  ).items[0];
  if (first === undefined) return { status: "none" };
  return {
    status: "found",
    title: first.title,
    due: dueDateText(first),
    dueNote: duePhrase(first, deps.now),
    href: hrefFor(screenById("owner.obligation"), { businessId, obligationId: first.id }),
  };
}

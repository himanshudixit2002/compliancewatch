import type {
  Applicability,
  ChangeImpact,
  ImpactBusiness,
  ImpactFanOut,
  ResultCounts,
} from "@/entities/applicability/types";
import type { Business } from "@/entities/business/types";
import type { BulkNotificationResult, BulkOutcome } from "@/entities/notification/types";
import { t, type MessageKey } from "@/shared/i18n";
import { LOCALE, formatDate } from "@/shared/lib/dates";
import { withQuery } from "@/shared/lib/url";
import type { BulkSummary } from "../ui/bulk-shared";

/**
 * A CA firm's affected clients in words: the change's counts over every business of the firm with
 * a decision of the version, how far its fan-out got, each client (the legal entity at the top of
 * its businesses' lineage) named from the profile service with its businesses' latest decisions,
 * and what a bulk change card did for each business it named.
 */
export const IMPACT_PAGE_SIZE = 50;

/** The clients to list: the affected ones (the default), one other result, or every one. */
export type ResultFilter = Applicability | "all";

export const RESULT_FILTERS: readonly ResultFilter[] = [
  "applies",
  "unsure",
  "not_applicable",
  "all",
];

const FILTER_LABEL: Readonly<Record<ResultFilter, MessageKey>> = {
  applies: "changeImpact.filter.applies",
  unsure: "changeImpact.filter.unsure",
  not_applicable: "changeImpact.filter.notApplicable",
  all: "changeImpact.filter.all",
};

const FAN_OUT_STATUS: Readonly<Record<ImpactFanOut["status"], MessageKey>> = {
  running: "changeImpact.fanOut.running",
  held: "changeImpact.fanOut.held",
  paused: "changeImpact.fanOut.paused",
  completed: "changeImpact.fanOut.completed",
  cancelled: "changeImpact.fanOut.cancelled",
  disabled: "changeImpact.fanOut.disabled",
  failed: "changeImpact.fanOut.failed",
};

const OUTCOME_LABEL: Readonly<Record<BulkOutcome, MessageKey>> = {
  queued: "changeImpact.outcome.queued",
  duplicate: "changeImpact.outcome.duplicate",
  no_recipient: "changeImpact.outcome.noRecipient",
  not_affected: "changeImpact.outcome.notAffected",
};

const COUNT = new Intl.NumberFormat(LOCALE);

export function filterLabel(filter: ResultFilter): string {
  return t(FILTER_LABEL[filter]);
}

export function outcomeLabel(outcome: BulkOutcome): string {
  return t(OUTCOME_LABEL[outcome]);
}

function isFilter(value: string): value is ResultFilter {
  return (RESULT_FILTERS as readonly string[]).includes(value);
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

/** The result filter and the engine's cursor in the address. */
export function readImpactQuery(query: Query): { result: ResultFilter; cursor: string | null } {
  const result = first(query.result);
  const cursor = first(query.cursor);
  return {
    result: isFilter(result) ? result : "applies",
    cursor:
      cursor === "" || cursor.length > 512 || !/^[A-Za-z0-9_-]+$/.test(cursor) ? null : cursor,
  };
}

/** The screen's address for a filter (the default left out) and a page. */
export function impactHref(pathname: string, result: ResultFilter, cursor?: string): string {
  return withQuery(pathname, {
    result: result === "applies" ? undefined : result,
    cursor,
  });
}

export interface CountsView {
  applies: string;
  unsure: string;
  notApplicable: string;
  total: string;
}

export function countsView(counts: ResultCounts): CountsView {
  return {
    applies: COUNT.format(counts.applies),
    unsure: COUNT.format(counts.unsure),
    notApplicable: COUNT.format(counts.notApplicable),
    total: COUNT.format(counts.applies + counts.unsure + counts.notApplicable),
  };
}

/** How far the version's fan-out over every tenant got, or that it had none. */
export function fanOutLine(fanOut: ImpactFanOut | null): string {
  if (fanOut === null) return t("changeImpact.fanOut.none");
  return t("changeImpact.fanOut.line", {
    status: t(FAN_OUT_STATUS[fanOut.status]),
    evaluated: COUNT.format(fanOut.evaluated),
    total: COUNT.format(fanOut.businessesTotal),
  });
}

/** A client's business named by its GSTIN and name, or as the client itself by its PAN. */
export function nodeLabel(business: Business | null, nodeId: string): string {
  if (business === null) return nodeId;
  if (business.id === nodeId) return t("changeImpact.node.entity", { pan: business.pan });
  const registration = business.registrations.find((node) => node.id === nodeId);
  return registration === undefined
    ? nodeId
    : t("changeImpact.node.registration", { gstin: registration.key, name: registration.name });
}

export interface ImpactBusinessRow {
  businessId: string;
  label: string;
  result: Applicability;
  needsReview: boolean;
  confidence: string;
  decided: string;
  decidedIso: string;
}

export interface ClientRow {
  entityId: string;
  /** The client's name with its PAN, or its id when the profile service did not answer. */
  name: string;
  businesses: readonly ImpactBusinessRow[];
}

function businessRow(row: ImpactBusiness, client: Business | null): ImpactBusinessRow {
  return {
    businessId: row.businessId,
    label: nodeLabel(client, row.businessId),
    result: row.result,
    needsReview: row.needsReview,
    confidence: `${Math.round(row.confidence * 100)}%`,
    decided: formatDate(row.decidedAt),
    decidedIso: row.decidedAt,
  };
}

export function clientRows(
  impact: Pick<ChangeImpact, "clients">,
  names: ReadonlyMap<string, Business>,
): ClientRow[] {
  return impact.clients.map((client) => {
    const business = names.get(client.entityId) ?? null;
    return {
      entityId: client.entityId,
      name:
        business === null
          ? client.entityId
          : t("changeImpact.client", { name: business.name, pan: business.pan }),
      businesses: client.businesses.map((row) => businessRow(row, business)),
    };
  });
}

function peopleText(entry: BulkNotificationResult["businesses"][number]): string {
  if (entry.outcome === "queued") return t("changeImpact.people.queued", { count: entry.queued });
  if (entry.outcome === "duplicate") {
    return t("changeImpact.people.duplicate", { count: entry.duplicates });
  }
  if (entry.outcome === "no_recipient") {
    return entry.unreachable === 0
      ? t("changeImpact.people.nobody")
      : t("changeImpact.people.unreachable", { count: entry.unreachable });
  }
  return t("changeImpact.people.notAffected");
}

/** What a bulk change card did, for the panel: the counts in a sentence and each business. */
export function bulkSummary(result: BulkNotificationResult, replayed: boolean): BulkSummary {
  const counts = t("changeImpact.sent.counts", {
    told: result.businesses.length,
    queued: result.queued,
    cards: result.notificationsQueued,
    duplicate: result.skippedDuplicate,
    nobody: result.skippedNoRecipient,
    notAffected: result.skippedNotAffected,
  });
  return {
    message: `${replayed ? t("changeImpact.sent.replayed") : t("changeImpact.sent.done")} ${counts}`,
    replayed,
    businesses: result.businesses.map((entry) => ({
      businessId: entry.businessId,
      outcome: entry.outcome,
      outcomeLabel: outcomeLabel(entry.outcome),
      people: peopleText(entry),
    })),
  };
}

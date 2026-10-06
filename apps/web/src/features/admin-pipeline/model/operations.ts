import {
  CRAWL_STATUSES,
  CRAWL_TRIGGERS,
  DOCUMENT_STATUSES,
  DOCUMENT_TYPES,
  type Classification,
  type CrawlRun,
  type CrawlStatus,
  type CrawlTrigger,
  type DocumentStatus,
  type DocumentType,
  type Extraction,
  type OutboxEvent,
  type Page,
  type PipelineDocument,
} from "@/entities/pipeline/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate, formatDateTime, isDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";
import type { FilterChip } from "@/shared/ui/filter-chips";
import { documentTypeLabel, sourceHref } from "@/shared/ui/pipeline";
import type { EventRow } from "../ui/pipeline-shared";

export type { EventRow } from "../ui/pipeline-shared";

/**
 * The pipeline page: three views of the pipeline's operations, one at a time, each a GET address
 * (filters and the pipeline's cursor in the query; keys, statuses and dates are not personal
 * data), so a filtered page can be shared:
 *
 *   view=runs       every source's crawl runs, the latest first, of a source, a status, a trigger
 *   view=documents  every source's documents, the latest fetch first, of a status, a source, a
 *                   type and publication dates, each with how the pipeline reads it
 *   view=outbox     the outbox rows the relay gave up on, of a topic, the newest dead first
 *
 * A source, a date or a topic that cannot be one is marked on its field and nothing is read; a
 * status, trigger or type the select does not offer is read as none.
 */
export const PIPELINE_VIEWS = ["runs", "documents", "outbox"] as const;

export type PipelineViewName = (typeof PIPELINE_VIEWS)[number];

export const PIPELINE_PARAMS = {
  view: "view",
  source: "source",
  status: "status",
  trigger: "trigger",
  type: "type",
  from: "from",
  to: "to",
  topic: "topic",
  cursor: "cursor",
} as const;

/** Rows a page asks the pipeline for. */
export const PIPELINE_PAGE_SIZE = 25;

const SOURCE_KEY = /^[a-z][a-z0-9_]{0,62}$/;
const TOPIC = /^[a-z][a-z0-9_.-]{0,119}$/;

export interface RunFilter {
  source: string | null;
  status: CrawlStatus | null;
  trigger: CrawlTrigger | null;
  cursor: string | null;
}

export interface DocumentFilter {
  status: DocumentStatus | null;
  source: string | null;
  type: DocumentType | null;
  from: string | null;
  to: string | null;
  cursor: string | null;
}

export interface OutboxFilter {
  topic: string | null;
  cursor: string | null;
}

export type PipelineFilter =
  | { view: "runs"; filter: RunFilter }
  | { view: "documents"; filter: DocumentFilter }
  | { view: "outbox"; filter: OutboxFilter };

/** The query read: the filter, and the fields that cannot be what they say (nothing is read). */
export interface PipelineRead {
  current: PipelineFilter;
  /** Field name to the value as typed. */
  invalid: Readonly<Record<string, string>>;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

function member<T extends string>(list: readonly T[], value: string): T | null {
  return (list as readonly string[]).includes(value) ? (value as T) : null;
}

function cursorOf(query: Query): string | null {
  const cursor = first(query, PIPELINE_PARAMS.cursor);
  return cursor === "" || cursor.length > 512 ? null : cursor;
}

export function readPipelineQuery(query: Query): PipelineRead {
  const view = member(PIPELINE_VIEWS, first(query, PIPELINE_PARAMS.view)) ?? "runs";
  const invalid: Record<string, string> = {};
  const cursor = cursorOf(query);
  const source = first(query, PIPELINE_PARAMS.source);
  if (view !== "outbox" && source !== "" && !SOURCE_KEY.test(source)) {
    invalid[PIPELINE_PARAMS.source] = source;
  }
  const sourceKey = source === "" || !SOURCE_KEY.test(source) ? null : source;
  if (view === "runs") {
    return {
      current: {
        view,
        filter: {
          source: sourceKey,
          status: member(CRAWL_STATUSES, first(query, PIPELINE_PARAMS.status)),
          trigger: member(CRAWL_TRIGGERS, first(query, PIPELINE_PARAMS.trigger)),
          cursor,
        },
      },
      invalid,
    };
  }
  if (view === "documents") {
    const from = first(query, PIPELINE_PARAMS.from);
    const to = first(query, PIPELINE_PARAMS.to);
    if (from !== "" && !isDateKey(from)) invalid[PIPELINE_PARAMS.from] = from;
    if (to !== "" && !isDateKey(to)) invalid[PIPELINE_PARAMS.to] = to;
    if (isDateKey(from) && isDateKey(to) && from > to) invalid[PIPELINE_PARAMS.to] = to;
    return {
      current: {
        view,
        filter: {
          status: member(DOCUMENT_STATUSES, first(query, PIPELINE_PARAMS.status)),
          source: sourceKey,
          type: member(DOCUMENT_TYPES, first(query, PIPELINE_PARAMS.type)),
          from: isDateKey(from) ? from : null,
          to: isDateKey(to) ? to : null,
          cursor,
        },
      },
      invalid,
    };
  }
  const topic = first(query, PIPELINE_PARAMS.topic);
  if (topic !== "" && !TOPIC.test(topic)) invalid[PIPELINE_PARAMS.topic] = topic;
  return {
    current: { view, filter: { topic: TOPIC.test(topic) ? topic : null, cursor } },
    invalid,
  };
}

/** The page's address for a filter. */
export function pipelineHref(current: PipelineFilter, cursor: string | null = null): string {
  const base = hrefFor(screenById("admin.pipeline"));
  const { filter } = current;
  if (current.view === "runs") {
    const runs = filter as RunFilter;
    return withQuery(base, {
      [PIPELINE_PARAMS.view]: undefined,
      [PIPELINE_PARAMS.source]: runs.source ?? undefined,
      [PIPELINE_PARAMS.status]: runs.status ?? undefined,
      [PIPELINE_PARAMS.trigger]: runs.trigger ?? undefined,
      [PIPELINE_PARAMS.cursor]: cursor ?? undefined,
    });
  }
  if (current.view === "documents") {
    const documents = filter as DocumentFilter;
    return withQuery(base, {
      [PIPELINE_PARAMS.view]: "documents",
      [PIPELINE_PARAMS.status]: documents.status ?? undefined,
      [PIPELINE_PARAMS.source]: documents.source ?? undefined,
      [PIPELINE_PARAMS.type]: documents.type ?? undefined,
      [PIPELINE_PARAMS.from]: documents.from ?? undefined,
      [PIPELINE_PARAMS.to]: documents.to ?? undefined,
      [PIPELINE_PARAMS.cursor]: cursor ?? undefined,
    });
  }
  const outbox = filter as OutboxFilter;
  return withQuery(base, {
    [PIPELINE_PARAMS.view]: "outbox",
    [PIPELINE_PARAMS.topic]: outbox.topic ?? undefined,
    [PIPELINE_PARAMS.cursor]: cursor ?? undefined,
  });
}

const VIEW_LABELS: Readonly<Record<PipelineViewName, MessageKey>> = {
  runs: "adminPipeline.view.runs",
  documents: "adminPipeline.view.documents",
  outbox: "adminPipeline.view.outbox",
};

const EMPTY_FILTERS: { [V in PipelineViewName]: Extract<PipelineFilter, { view: V }> } = {
  runs: { view: "runs", filter: { source: null, status: null, trigger: null, cursor: null } },
  documents: {
    view: "documents",
    filter: { status: null, source: null, type: null, from: null, to: null, cursor: null },
  },
  outbox: { view: "outbox", filter: { topic: null, cursor: null } },
};

/** One chip per view, each on its first page with no filter. */
export function viewChips(current: PipelineViewName): FilterChip[] {
  return PIPELINE_VIEWS.map((view) => ({
    key: view,
    label: t(VIEW_LABELS[view]),
    href: pipelineHref(EMPTY_FILTERS[view]),
    current: view === current,
  }));
}

/** Whether the filter narrows the list (an empty narrowed list says so). */
export function isFiltered(current: PipelineFilter): boolean {
  const values = Object.entries(current.filter).filter(([key]) => key !== "cursor");
  return values.some(([, value]) => value !== null);
}

// ---- Documents ----------------------------------------------------------------------------------

const CLASSIFIERS: Readonly<Record<string, MessageKey>> = {
  triage: "adminPipeline.classifier.triage",
  retry: "adminPipeline.classifier.retry",
};

/** detector@1 is the rule-based detector; triage and retry are a person's decision. */
export function classifierLabel(classifier: string): string {
  if (classifier.startsWith("detector@")) {
    return t("adminPipeline.classifier.detector", { version: classifier });
  }
  const key = CLASSIFIERS[classifier];
  return key === undefined ? classifier : t(key);
}

const RELEVANCE: Readonly<Record<string, MessageKey>> = {
  relevant: "adminPipeline.relevance.relevant",
  irrelevant: "adminPipeline.relevance.irrelevant",
};

const CONFIDENCE: Readonly<Record<string, MessageKey>> = {
  certain: "adminPipeline.confidence.certain",
  default: "adminPipeline.confidence.default",
  conflict: "adminPipeline.confidence.conflict",
};

const ROUTES: Readonly<Record<string, MessageKey>> = {
  extract: "adminPipeline.route.extract",
  reference: "adminPipeline.route.reference",
  irrelevant: "adminPipeline.route.irrelevant",
  triage: "adminPipeline.route.triage",
};

function worded(table: Readonly<Record<string, MessageKey>>, value: string): string {
  const key = table[value];
  return key === undefined ? humanise(value) : t(key);
}

export interface ClassificationView {
  by: string;
  /** The person's id, for a triage or a retry ("you" when it is the signed-in user). */
  decidedBy: string | null;
  type: string;
  relevance: string;
  confidence: string;
  route: string;
  reasons: readonly string[];
  at: string;
  atIso: string;
  taskId: string | null;
}

export function classificationView(
  classification: Classification,
  userId: string | null,
): ClassificationView {
  return {
    by: classifierLabel(classification.classifier),
    decidedBy:
      classification.decidedBy === null
        ? null
        : classification.decidedBy === userId
          ? t("adminPipeline.you")
          : classification.decidedBy,
    type: documentTypeLabel(classification.docType),
    relevance: worded(RELEVANCE, classification.relevance),
    confidence: worded(CONFIDENCE, classification.confidence),
    route: worded(ROUTES, classification.route),
    reasons: classification.reasons,
    at: formatDateTime(classification.classifiedAt),
    atIso: classification.classifiedAt,
    taskId: classification.taskId,
  };
}

export interface ExtractionView {
  outcome: string;
  candidateId: string;
  model: string;
  promptVersion: string;
  issues: string;
  needsReview: boolean;
  at: string;
  atIso: string;
}

export function extractionView(extraction: Extraction): ExtractionView {
  return {
    outcome:
      extraction.outcome === "extracted"
        ? t("adminPipeline.extraction.extracted")
        : extraction.outcome === "unparseable"
          ? t("adminPipeline.extraction.unparseable")
          : humanise(extraction.outcome),
    candidateId: extraction.candidateId,
    model: extraction.model,
    promptVersion: extraction.promptVersion,
    issues: t("adminPipeline.extraction.issues", { count: extraction.issueCount }),
    needsReview: extraction.needsReview,
    at: formatDateTime(extraction.extractedAt),
    atIso: extraction.extractedAt,
  };
}

export interface DocumentRow {
  documentId: string;
  href: string;
  title: string;
  externalRef: string;
  sourceKey: string;
  sourceHref: string;
  readAs: string;
  status: string;
  classification: ClassificationView | null;
  extraction: ExtractionView | null;
  published: string | null;
  fetched: string;
  fetchedIso: string;
}

export function documentPageHref(documentId: string): string {
  return hrefFor(screenById("admin.pipeline.document"), { documentId });
}

export function documentTitle(document: { title: string; externalRef: string }): string {
  if (document.title !== "") return document.title;
  if (document.externalRef !== "") return document.externalRef;
  return t("adminPipeline.untitled");
}

export function documentRow(document: PipelineDocument, userId: string | null): DocumentRow {
  return {
    documentId: document.documentId,
    href: documentPageHref(document.documentId),
    title: documentTitle(document),
    externalRef: document.externalRef,
    sourceKey: document.sourceKey,
    sourceHref: sourceHref(document.sourceKey),
    readAs: documentTypeLabel(document.readAs),
    status: document.status,
    classification:
      document.classification === null ? null : classificationView(document.classification, userId),
    extraction: document.extraction === null ? null : extractionView(document.extraction),
    published: document.publishedOn === null ? null : formatDate(document.publishedOn),
    fetched: formatDateTime(document.fetchedAt),
    fetchedIso: document.fetchedAt,
  };
}

// ---- Outbox -------------------------------------------------------------------------------------

function summaryValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return t("common.none");
  return JSON.stringify(value);
}

export function eventRow(event: OutboxEvent): EventRow {
  return {
    eventId: event.eventId,
    topic: event.topic,
    key: event.key,
    attempts: event.attempts,
    lastError: event.lastError,
    deadAt: event.deadAt === null ? null : formatDateTime(event.deadAt),
    deadAtIso: event.deadAt,
    occurred: formatDateTime(event.occurredAt),
    occurredIso: event.occurredAt,
    schemaVersion: event.schemaVersion,
    payloadBytes: event.payloadBytes,
    summary: Object.entries(event.summary).map(
      ([name, value]) => [name, summaryValue(value)] as const,
    ),
  };
}

// ---- The page -----------------------------------------------------------------------------------

export interface PagedRows<T> {
  rows: T[];
  nextHref: string | null;
  firstHref: string | null;
  /** This page is a later one. */
  later: boolean;
}

export function pagedRows<D, T>(
  current: PipelineFilter,
  page: Page<D>,
  row: (item: D) => T,
): PagedRows<T> {
  const cursor = current.filter.cursor;
  return {
    rows: page.items.map(row),
    nextHref: page.nextCursor === null ? null : pipelineHref(current, page.nextCursor),
    firstHref: cursor === null ? null : pipelineHref(current),
    later: cursor !== null,
  };
}

export type PipelineList =
  | { view: "runs"; list: PagedRows<CrawlRun> }
  | { view: "documents"; list: PagedRows<DocumentRow> }
  | { view: "outbox"; list: PagedRows<EventRow> };

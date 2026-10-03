import type { Tone } from "@compliancewatch/ui";
import type { rulebook } from "@compliancewatch/contracts/openapi";
import { t, type MessageKey } from "@/shared/i18n";
import { LOCALE } from "@/shared/lib/dates";

/**
 * The sources screen: the regulator sites the pipeline fetches documents from and how each one's
 * fetching stands. `GET /v1/pipeline/sources` has no committed spec yet, so these are plain
 * types; instants are ISO strings and the view formats them in IST.
 */

/** The kind of document a source lists, as the rulebook's spec names it. */
export type SourceDocumentType = rulebook.components["schemas"]["DocumentType"];

/** Healthy when the last fetch succeeded, failing when it did not, paused while switched off. */
export type SourceStatus = "healthy" | "fetching" | "failing" | "paused";

export const SOURCE_STATUSES: readonly SourceStatus[] = [
  "healthy",
  "fetching",
  "failing",
  "paused",
];

/** The form field that carries a source's key to the fetch action. */
export const SOURCE_KEY_FIELD = "source_key";

/** One source the pipeline fetches from. */
export interface PipelineSource {
  /** The stable key, such as "example_notices"; the pipeline's routes address a source by it. */
  key: string;
  name: string;
  /** The site it is fetched from, such as "notices.example.com". */
  site: string;
  documentType: SourceDocumentType;
  status: SourceStatus;
  /** When the last fetch finished; null before the first one. */
  lastFetchedAt: string | null;
  /** Documents collected from it so far. */
  documentCount: number;
}

/** The figures in the summary row. */
export interface SourceCounts {
  total: number;
  healthy: number;
  failing: number;
}

const STATUS_LABEL: Readonly<Record<SourceStatus, MessageKey>> = {
  healthy: "adminSources.status.healthy",
  fetching: "adminSources.status.fetching",
  failing: "adminSources.status.failing",
  paused: "adminSources.status.paused",
};

const STATUS_TONE: Readonly<Record<SourceStatus, Tone>> = {
  healthy: "success",
  fetching: "info",
  failing: "danger",
  paused: "neutral",
};

const TYPE_LABEL: Readonly<Record<SourceDocumentType, MessageKey>> = {
  notification: "adminSources.type.notification",
  circular: "adminSources.type.circular",
  press_release: "adminSources.type.pressRelease",
  act_amendment: "adminSources.type.actAmendment",
};

const COUNT_FORMAT = new Intl.NumberFormat(LOCALE);

export function sourceStatusLabel(status: SourceStatus): string {
  return t(STATUS_LABEL[status]);
}

export function sourceStatusTone(status: SourceStatus): Tone {
  return STATUS_TONE[status];
}

export function documentTypeLabel(type: SourceDocumentType): string {
  return t(TYPE_LABEL[type]);
}

/** A count with Indian digit grouping: 1,23,456. */
export function formatCount(count: number): string {
  return COUNT_FORMAT.format(count);
}

/** A fetch can be asked for unless one is already running. */
export function canFetch(source: Pick<PipelineSource, "status">): boolean {
  return source.status !== "fetching";
}

export function sourceCounts(sources: readonly PipelineSource[]): SourceCounts {
  return {
    total: sources.length,
    healthy: sources.filter((source) => source.status === "healthy").length,
    failing: sources.filter((source) => source.status === "failing").length,
  };
}

import type { Tone } from "@compliancewatch/ui";
import type {
  CrawlRun,
  Freshness,
  FreshnessState,
  PipelineSource,
  SourceStatus,
} from "@/entities/pipeline/types";
import { screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { LOCALE, formatDate, formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import {
  documentTypeLabel,
  runStatusLabel,
  runStatusTone,
  runTriggerLabel,
  sourceHref,
} from "@/shared/ui/pipeline";

/**
 * The source registry's view: each source the pipeline reads with its adapter type, regulator and
 * site, the documents it holds, how it stands (healthy, fetching, failing, paused), whether the
 * schedule may crawl it (enabled, not paused, listing documents at all), its cadence, its
 * freshness against that cadence, its last listing and latest run, and its watermark; and above
 * the list, what the web server knows of the crawl switch: the flag as the registry declares it
 * (off by default) and the schedule's latest crawl, the only sign of the pipeline's own value it
 * can read.
 */
const STATUS_LABELS: Readonly<Record<SourceStatus, MessageKey>> = {
  healthy: "adminSources.status.healthy",
  fetching: "adminSources.status.fetching",
  failing: "adminSources.status.failing",
  paused: "adminSources.status.paused",
};

const STATUS_TONES: Readonly<Record<SourceStatus, Tone>> = {
  healthy: "success",
  fetching: "info",
  failing: "danger",
  paused: "neutral",
};

const FRESHNESS_LABELS: Readonly<Record<FreshnessState, MessageKey>> = {
  fresh: "adminSources.freshness.fresh",
  late: "adminSources.freshness.late",
  stale: "adminSources.freshness.stale",
  never: "adminSources.freshness.never",
};

const FRESHNESS_TONES: Readonly<Record<FreshnessState, Tone>> = {
  fresh: "success",
  late: "warning",
  stale: "danger",
  never: "neutral",
};

export function sourceStatusLabel(status: string): string {
  return Object.hasOwn(STATUS_LABELS, status)
    ? t(STATUS_LABELS[status as SourceStatus])
    : humanise(status);
}

export function sourceStatusTone(status: string): Tone {
  return Object.hasOwn(STATUS_TONES, status) ? STATUS_TONES[status as SourceStatus] : "neutral";
}

export function freshnessLabel(state: string): string {
  return Object.hasOwn(FRESHNESS_LABELS, state)
    ? t(FRESHNESS_LABELS[state as FreshnessState])
    : humanise(state);
}

export function freshnessTone(state: string): Tone {
  return Object.hasOwn(FRESHNESS_TONES, state)
    ? FRESHNESS_TONES[state as FreshnessState]
    : "neutral";
}

/** "45 s", "12 min", "2 h", "2 h 30 min", "1 d", "1 d 6 h": a length of time, rounded down. */
export function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return t("adminSources.duration.seconds", { count: whole });
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) return t("adminSources.duration.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest === 0
      ? t("adminSources.duration.hours", { hours })
      : t("adminSources.duration.hoursMinutes", { hours, minutes: rest });
  }
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours === 0
    ? t("adminSources.duration.days", { days })
    : t("adminSources.duration.daysHours", { days, hours: restHours });
}

const COUNT = new Intl.NumberFormat(LOCALE);
const CADENCES = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });

/** A count with Indian digit grouping: 1,23,456. */
export function formatCount(count: number): string {
  return COUNT.format(count);
}

/** "Every 2 h". */
export function cadenceText(seconds: number): string {
  return t("adminSources.cadence", { duration: formatSeconds(seconds) });
}

/**
 * How long since a crawl listed the source, in time and in cadences; null before the first, when
 * the freshness label ("Never listed") says it all.
 */
export function freshnessText(freshness: Freshness): string | null {
  if (freshness.ageSeconds === null) return null;
  const age = formatSeconds(freshness.ageSeconds);
  return freshness.cadences === null
    ? t("adminSources.freshness.age", { age })
    : t("adminSources.freshness.ageCadences", {
        age,
        cadences: CADENCES.format(freshness.cadences),
      });
}

/** Whether the schedule may crawl the source, in a word or two, for the list. */
export function switchesShort(
  source: Pick<PipelineSource, "enabled" | "paused" | "listable">,
): string {
  if (!source.listable) return t("adminSources.switchesShort.uploadOnly");
  if (!source.enabled && source.paused) return t("adminSources.switchesShort.disabledPaused");
  if (!source.enabled) return t("adminSources.switchesShort.disabled");
  if (source.paused) return t("adminSources.switchesShort.paused");
  return t("adminSources.switchesShort.enabled");
}

/** Whether the schedule may crawl the source, in words. */
export function switchesText(
  source: Pick<PipelineSource, "enabled" | "paused" | "listable">,
): string {
  if (!source.listable) return t("adminSources.switches.uploadOnly");
  if (!source.enabled && source.paused) return t("adminSources.switches.disabledPaused");
  if (!source.enabled) return t("adminSources.switches.disabled");
  if (source.paused) return t("adminSources.switches.paused");
  return t("adminSources.switches.enabled");
}

export interface RunSummary {
  status: string;
  started: string;
  startedIso: string;
  statusLabel: string;
  statusTone: Tone;
  triggerLabel: string;
  backfill: boolean;
}

export function runSummary(run: CrawlRun): RunSummary {
  return {
    status: run.status,
    started: formatDateTime(run.startedAt),
    startedIso: run.startedAt,
    statusLabel: runStatusLabel(run.status),
    statusTone: runStatusTone(run.status),
    triggerLabel: runTriggerLabel(run.trigger),
    backfill: run.trigger === "backfill",
  };
}

export interface SourceRow {
  key: string;
  name: string;
  href: string;
  adapterType: string;
  regulator: string | null;
  site: string | null;
  docType: string;
  documents: string;
  status: SourceStatus;
  statusLabel: string;
  statusTone: Tone;
  switches: string;
  uploadOnly: boolean;
  cadence: string;
  /** The detail is null before the first listing, which the label says already. */
  freshness: { state: FreshnessState; label: string; tone: Tone; detail: string | null };
  lastListed: { text: string; iso: string } | null;
  latestRun: RunSummary | null;
  watermark: string | null;
  lastError: string;
}

export function sourceRow(source: PipelineSource): SourceRow {
  return {
    key: source.key,
    name: source.name,
    href: sourceHref(source.key),
    adapterType: source.adapterType,
    regulator: source.regulator,
    site: source.site,
    docType: documentTypeLabel(source.docType),
    documents: formatCount(source.documentCount),
    status: source.status,
    statusLabel: sourceStatusLabel(source.status),
    statusTone: sourceStatusTone(source.status),
    switches: switchesShort(source),
    uploadOnly: !source.listable,
    cadence: cadenceText(source.cadenceSeconds),
    freshness: {
      state: source.freshness.state,
      label: freshnessLabel(source.freshness.state),
      tone: freshnessTone(source.freshness.state),
      detail: freshnessText(source.freshness),
    },
    lastListed:
      source.lastFetchAt === null
        ? null
        : { text: formatDateTime(source.lastFetchAt), iso: source.lastFetchAt },
    latestRun: source.latestRun === null ? null : runSummary(source.latestRun),
    watermark: source.watermark === null ? null : formatDate(source.watermark),
    lastError: source.lastError,
  };
}

export interface SourceCounts {
  total: number;
  failing: number;
  /** Listing sources more than a cadence behind (late or stale). */
  behind: number;
  uploadOnly: number;
}

export function sourceCounts(sources: readonly PipelineSource[]): SourceCounts {
  return {
    total: sources.length,
    failing: sources.filter((source) => source.status === "failing").length,
    behind: sources.filter(
      (source) =>
        source.listable &&
        (source.freshness.state === "late" || source.freshness.state === "stale"),
    ).length,
    uploadOnly: sources.filter((source) => !source.listable).length,
  };
}

/** The crawl switch as the flag registry declares it (the pipeline holds the value). */
export interface CrawlFlag {
  name: string;
  variable: string;
  defaultOn: boolean;
  owner: string;
}

/** The schedule's latest crawl, the one sign of the switch's value the web server can read. */
export type LatestScheduled =
  | { kind: "none" }
  | { kind: "run"; sourceKey: string | null; summary: RunSummary }
  | { kind: "error"; message: string; correlationId: string | null };

export interface CrawlState {
  flag: CrawlFlag;
  latestScheduled: LatestScheduled;
}

export interface SourcesView {
  rows: SourceRow[];
  counts: SourceCounts;
  crawl: CrawlState;
}

/** The list sorted as the pipeline lists it (by key), with its counts and the crawl's state. */
export function sourcesView(sources: readonly PipelineSource[], crawl: CrawlState): SourcesView {
  return { rows: sources.map(sourceRow), counts: sourceCounts(sources), crawl };
}

/** Why the page offers no way to add a source: its registry entry, in the registry's words. */
export interface AddSourceNote {
  title: string;
  notes: string;
  routes: readonly string[];
}

export function addSourceNote(): AddSourceNote {
  const entry = screenById("admin.sources.add");
  return {
    title: entry.title,
    notes: entry.notes ?? "",
    routes: entry.uses.map((route) => `${route.method} ${route.path}`),
  };
}
